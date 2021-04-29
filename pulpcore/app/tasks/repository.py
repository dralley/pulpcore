from concurrent.futures import ThreadPoolExecutor
from gettext import gettext as _
from logging import getLogger
import asyncio
import hashlib

from django.core.files.storage import default_storage
from django.db import transaction
from rest_framework.serializers import ValidationError

from pulpcore.app import models
from pulpcore.app.models import ProgressReport

log = getLogger(__name__)


CHUNK_SIZE = 1024 * 1024  # 1 Mb


def delete_version(pk):
    """
    Delete a repository version by squashing its changes with the next newer version. This ensures
    that the content set for each version stays the same.

    There must be a newer version to squash into. If we deleted the latest version, the next content
    change would create a new one of the same number, which would violate the immutability
    guarantee.

    Args:
        pk (uuid): the primary key for a RepositoryVersion to delete

    Raises:
        models.RepositoryVersion.DoesNotExist: if there is not a newer version to squash into.
            TODO: something more friendly
        ValidationError: if there's one repo version
    """
    with transaction.atomic():
        try:
            version = models.RepositoryVersion.objects.get(pk=pk)
        except models.RepositoryVersion.DoesNotExist:
            log.info(_("The repository version was not found. Nothing to do."))
            return

        if version.repository.versions.complete().count() <= 1:
            raise ValidationError(
                _(
                    "Cannot delete repository version. Repositories must have at least one "
                    "repository version."
                )
            )

        log.info(
            _("Deleting and squashing version {num} of repository '{repo}'").format(
                num=version.number, repo=version.repository.name
            )
        )

        version.delete()


async def _repair_artifact(artifact, repaired=None):
    remote_sources = artifact.remote_sources.all()

    if not remote_sources:
        log.warn(_("Artifact {} is unrepairable - no remote source".format(artifact)))
        return False

    for source in remote_sources:
        downloader = source.remote.cast().get_downloader(
            url=source.url,
            expected_size=artifact.expected_size(),
            expected_digests=artifact.expected_digests(),
        )
        dl_result = await downloader.run()
        if dl_result.artifact_attributes["sha256"] == artifact.sha256:
            with open(dl_result.path, "rb") as src:
                filename = artifact.file.name
                artifact.file.delete(save=False)
                artifact.file.save(filename, src, save=False)
            if repaired is not None:
                repaired.increment()
            return True
        log.warn(_("Redownload failed from {}.").format(source.url))

    return False


def _verify_artifact(artifact):
    try:
        # verify files digest
        hasher = hashlib.sha256()
        for chunk in artifact.file.chunks(CHUNK_SIZE):
            hasher.update(chunk)
        artifact.file.close()
        return hasher.hexdigest() == artifact.sha256
    except FileNotFoundError:
        return False


async def _repair_artifacts_for_content(subset=None, verify_checksums=True):
    loop = asyncio.get_event_loop()
    pending = set()

    query_set = models.Artifact.objects.is_immediate()

    if subset:
        # TODO: verify & maybe optimize
        content_artifacts = models.ContentArtifact.objects.filter(content__in=subset)
        query_set = query_set.filter(pk__in=content_artifacts.values_list("pk", flat=True))

    with ProgressReport(
        message="Identify missing units", code="repair.missing"
    ) as missing, ProgressReport(
        message="Identify corrupted units", code="repair.corrupted"
    ) as corrupted, ProgressReport(
        message="Repair corrupted units", code="repair.repaired"
    ) as repaired:

        with ThreadPoolExecutor(max_workers=2) as checksum_executor:
            for artifact in query_set.iterator():
                valid = await loop.run_in_executor(None, default_storage.exists, artifact.file.name)
                if not valid:
                    missing.increment()
                    log.warn(_("Missing file for {}").format(artifact))
                elif verify_checksums:
                    # default ThreadPoolExecutor uses num cores x 5 threads. Since we're doing
                    # such long and sequential reads, using too many threads might hurt more
                    # than help (on HDDs, maybe not on SSDs) by making the disk access pattern
                    # more random. Put it in a separate executor with limited threads.
                    # Should stay in (an) executor so that at least it doesn't completely block
                    # downloads.
                    valid = await loop.run_in_executor(
                        checksum_executor, _verify_artifact, artifact
                    )
                    if not valid:
                        corrupted.increment()
                        log.warn(_("Digest mismatch for {}").format(artifact))

                if not valid:
                    if len(pending) >= 5:  # Limit the number of concurrent repair tasks
                        done, pending = await asyncio.wait(
                            pending, return_when=asyncio.FIRST_COMPLETED
                        )
                        await asyncio.gather(*done)  # Clean up tasks
                    pending.add(asyncio.ensure_future(_repair_artifact(artifact, repaired)))
        await asyncio.gather(*pending)


def repair_version(repository_version_pk, verify_checksums):
    """
    Repair the artifacts associated with this repository version.

    Artifact files that have suffered from bit rot, were altered or have gone missing will be
    attempted to be refetched fron an associated upstream.

    Args:
        repository_version_pk (uuid): the primary key for a RepositoryVersion to delete
        verify_checksums (bool): whether to calculate and compare checksums for all artifacts
    """

    version = models.RepositoryVersion.objects.get(pk=repository_version_pk)

    log.info(
        _("Repairing version {num} of repository '{repo}'").format(
            num=version.number, repo=version.repository.name
        ),
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        _repair_artifacts_for_content(subset=version.content, verify_checksums=verify_checksums)
    )


def repair_all_artifacts(verify_checksums):
    """
    Repair all artifacts, globally.

    Artifact files that have suffered from bit rot, were altered or have gone missing will be
    attempted to be refetched fron an associated upstream.

    Args:
        verify_checksums (bool): whether to calculate and compare checksums for all artifacts
    """
    log.info(_("Repairing artifacts.'"))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(_repair_artifacts_for_content(verify_checksums=verify_checksums))


def add_and_remove(repository_pk, add_content_units, remove_content_units, base_version_pk=None):
    """
    Create a new repository version by adding and then removing content units.

    Args:
        repository_pk (int): The primary key for a Repository for which a new Repository Version
            should be created.
        add_content_units (list): List of PKs for :class:`~pulpcore.app.models.Content` that
            should be added to the previous Repository Version for this Repository.
        remove_content_units (list): List of PKs for:class:`~pulpcore.app.models.Content` that
            should be removed from the previous Repository Version for this Repository.
        base_version_pk (int): the primary key for a RepositoryVersion whose content will be used
            as the initial set of content for our new RepositoryVersion
    """
    repository = models.Repository.objects.get(pk=repository_pk).cast()

    if base_version_pk:
        base_version = models.RepositoryVersion.objects.get(pk=base_version_pk)
    else:
        base_version = None

    if "*" in remove_content_units:
        latest = repository.latest_version()
        if latest:
            remove_content_units = latest.content.values_list("pk", flat=True)
        else:
            remove_content_units = []

    with repository.new_version(base_version=base_version) as new_version:
        new_version.remove_content(models.Content.objects.filter(pk__in=remove_content_units))
        new_version.add_content(models.Content.objects.filter(pk__in=add_content_units))
