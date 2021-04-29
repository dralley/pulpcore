import asyncio
from collections import defaultdict
from gettext import gettext as _
import logging

from django.db import transaction

from pulpcore.plugin.exceptions import UnsupportedDigestValidationError
from pulpcore.plugin.models import Artifact, RemoteSource, ProgressReport

from .api import Stage

log = logging.getLogger(__name__)


def _check_for_forbidden_checksume_type(artifact):
    """Check if content doesn't have forbidden checksum type.

    If contains forbidden checksum type it will raise ValueError,
    otherwise it passes without returning anything.
    """
    for digest_type in Artifact.FORBIDDEN_DIGESTS:
        digest_value = getattr(artifact, digest_type)
        if digest_value:
            # To use shared message constant when #7988 is merged
            raise UnsupportedDigestValidationError(
                _(
                    "Artifact contains forbidden checksum type {}. You can allow it with "
                    "'ALLOWED_CONTENT_CHECKSUMS' setting."
                ).format(digest_type)
            )


class QueryExistingArtifacts(Stage):
    """
    A Stages API stage that replaces :attr:`DeclarativeContent.content` objects with already-saved
    :class:`~pulpcore.plugin.models.Artifact` objects.

    This stage expects :class:`~pulpcore.plugin.stages.DeclarativeContent` units from `self._in_q`
    and inspects their associated :class:`~pulpcore.plugin.stages.DeclarativeArtifact` objects. Each
    :class:`~pulpcore.plugin.stages.DeclarativeArtifact` object stores one
    :class:`~pulpcore.plugin.models.Artifact`.

    This stage inspects any unsaved :class:`~pulpcore.plugin.models.Artifact` objects and searches
    using their metadata for existing saved :class:`~pulpcore.plugin.models.Artifact` objects inside
    Pulp with the same digest value(s). Any existing :class:`~pulpcore.plugin.models.Artifact`
    objects found will replace their unsaved counterpart in the
    :class:`~pulpcore.plugin.stages.DeclarativeArtifact` object.

    Each :class:`~pulpcore.plugin.stages.DeclarativeContent` is sent to `self._out_q` after all of
    its :class:`~pulpcore.plugin.stages.DeclarativeArtifact` objects have been handled.

    This stage drains all available items from `self._in_q` and batches everything into one large
    call to the db for efficiency.
    """

    async def run(self):
        """
        The coroutine for this stage.

        Returns:
            The coroutine for this stage.
        """
        async for batch in self.batches():
            artifact_digests_by_type = defaultdict(list)

            # For each unsaved artifact, check its digests in the order of COMMON_DIGEST_FIELDS
            # and the first digest which is found is added to the list of digests of that type.
            # We assume that in general only one digest is provided and that it will be
            # sufficient to identify the Artifact.
            for d_content in batch:
                for d_artifact in d_content.d_artifacts:
                    if d_artifact.artifact._state.adding:
                        if not d_artifact.deferred_download:
                            _check_for_forbidden_checksume_type(d_artifact.artifact)
                        for digest_type in Artifact.COMMON_DIGEST_FIELDS:
                            digest_value = getattr(d_artifact.artifact, digest_type)
                            if digest_value:
                                artifact_digests_by_type[digest_type].append(digest_value)
                                break

            # For each type of digest, fetch all the existing Artifacts where digest "in"
            # the list we built earlier. Walk over all the artifacts again compare the
            # digest of the new artifact to those of the existing ones - if one matches,
            # swap it out with the existing one.
            for digest_type, digests in artifact_digests_by_type.items():
                query_params = {"{attr}__in".format(attr=digest_type): digests}
                existing_artifacts = Artifact.objects.filter(**query_params).only(digest_type)
                for d_content in batch:
                    for d_artifact in d_content.d_artifacts:
                        artifact_digest = getattr(d_artifact.artifact, digest_type)
                        if artifact_digest:
                            for result in existing_artifacts:
                                result_digest = getattr(result, digest_type)
                                if result_digest == artifact_digest:
                                    d_artifact.artifact = result
                                    break

            for d_content in batch:
                await self.put(d_content)


class ArtifactDownloader(Stage):
    """
    A Stages API stage to download :class:`~pulpcore.plugin.models.Artifact` files, but don't save
    the :class:`~pulpcore.plugin.models.Artifact` in the db.

    This stage downloads the file for any :class:`~pulpcore.plugin.models.Artifact` objects missing
    files and creates a new :class:`~pulpcore.plugin.models.Artifact` object from the downloaded
    file and its digest data. The new :class:`~pulpcore.plugin.models.Artifact` is not saved but
    added to the :class:`~pulpcore.plugin.stages.DeclarativeArtifact` object, replacing the likely
    incomplete :class:`~pulpcore.plugin.models.Artifact`.

    Each :class:`~pulpcore.plugin.stages.DeclarativeContent` is sent to `self._out_q` after all of
    its :class:`~pulpcore.plugin.stages.DeclarativeArtifact` objects have been handled.

    This stage creates a ProgressReport named 'Downloading Artifacts' that counts the number of
    downloads completed. Since it's a stream the total count isn't known until it's finished.

    This stage drains all available items from `self._in_q` and starts as many downloaders as
    possible (up to `download_concurrency` set on a Remote)

    Args:
        max_concurrent_content (int): The maximum number of
            :class:`~pulpcore.plugin.stages.DeclarativeContent` instances to handle simultaneously.
            Default is 200.
        args: unused positional arguments passed along to :class:`~pulpcore.plugin.stages.Stage`.
        kwargs: unused keyword arguments passed along to :class:`~pulpcore.plugin.stages.Stage`.
    """

    def __init__(self, max_concurrent_content=200, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_concurrent_content = max_concurrent_content

    async def run(self):
        """
        The coroutine for this stage.

        Returns:
            The coroutine for this stage.
        """

        def _add_to_pending(coro):
            nonlocal pending
            task = asyncio.ensure_future(coro)
            pending.add(task)
            return task

        #: (set): The set of unfinished tasks.  Contains the content
        #    handler tasks and may contain `content_get_task`.
        pending = set()

        content_iterator = self.items()

        #: (:class:`asyncio.Task`): The task that gets new content from `self._in_q`.
        #    Set to None if stage is shutdown.
        content_get_task = _add_to_pending(content_iterator.__anext__())

        with ProgressReport(
            message="Downloading Artifacts", code="sync.downloading.artifacts"
        ) as pb:
            try:
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if task is content_get_task:
                            try:
                                _add_to_pending(self._handle_content_unit(task.result()))
                            except StopAsyncIteration:
                                # previous stage is finished and we retrieved all
                                # content instances: shutdown
                                content_get_task = None
                        else:
                            pb.done += task.result()  # download_count
                            pb.save()

                    if content_get_task and content_get_task not in pending:  # not yet shutdown
                        if len(pending) < self.max_concurrent_content:
                            content_get_task = _add_to_pending(content_iterator.__anext__())
            except asyncio.CancelledError:
                # asyncio.wait does not cancel its tasks when cancelled, we need to do this
                for future in pending:
                    future.cancel()
                raise

    async def _handle_content_unit(self, d_content):
        """Handle one content unit.

        Returns:
            The number of downloads
        """
        downloaders_for_content = []
        for d_artifact in d_content.d_artifacts:
            if d_artifact.artifact._state.adding and not d_artifact.deferred_download and not d_artifact.artifact.file:
                downloaders_for_content.append(d_artifact.download())

        if downloaders_for_content:
            await asyncio.gather(*downloaders_for_content)
        await self.put(d_content)
        return len(downloaders_for_content)


class ArtifactSaver(Stage):
    """
    A Stages API stage that saves any unsaved :attr:`DeclarativeArtifact.artifact` objects.

    This stage expects :class:`~pulpcore.plugin.stages.DeclarativeContent` units from `self._in_q`
    and inspects their associated :class:`~pulpcore.plugin.stages.DeclarativeArtifact` objects. Each
    :class:`~pulpcore.plugin.stages.DeclarativeArtifact` object stores one
    :class:`~pulpcore.plugin.models.Artifact`.

    Any unsaved :class:`~pulpcore.plugin.models.Artifact` objects are saved. Each
    :class:`~pulpcore.plugin.stages.DeclarativeContent` is sent to `self._out_q` after all of its
    :class:`~pulpcore.plugin.stages.DeclarativeArtifact` objects have been handled.

    This stage drains all available items from `self._in_q` and batches everything into one large
    call to the db for efficiency.
    """

    async def run(self):
        """
        The coroutine for this stage.

        Returns:
            The coroutine for this stage.
        """
        async for batch in self.batches():
            with transaction.atomic():
                da_to_save = []
                rs_to_save = []
                for d_content in batch:
                    for d_artifact in d_content.d_artifacts:
                        if d_artifact.artifact._state.adding:
                            if d_artifact.deferred_download:
                                if d_artifact.remote:
                                    rs = RemoteSource(
                                        url=d_artifact.url,
                                        artifact=d_artifact.artifact,
                                        remote=d_artifact.remote,
                                    )
                                    rs_to_save.append(rs)
                            else:
                                d_artifact.artifact.file = str(d_artifact.artifact.file)

                            da_to_save.append(d_artifact)

                if da_to_save:
                    for d_artifact, artifact in zip(
                        da_to_save,
                        Artifact.objects.bulk_get_or_create(
                            d_artifact.artifact for d_artifact in da_to_save
                        ),
                    ):
                        d_artifact.artifact = artifact
                if rs_to_save:
                    RemoteSource.objects.bulk_get_or_create(rs_to_save, ignore_conflicts=True)

            for d_content in batch:
                await self.put(d_content)
