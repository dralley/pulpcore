# https://docs.djangoproject.com/en/dev/topics/db/models/#organizing-models-in-a-package

# Must be imported first as other models depend on it
from .base import (  # noqa
    BaseModel,
    Label,
    MasterModel,
)

from .access_policy import (  # noqa
    AccessPolicy,
    AutoAddObjPermsMixin,
    AutoDeleteObjPermsMixin,
    Group,
)
from .acs import AlternateContentSource, AlternateContentSourcePath  # noqa
from .content import (  # noqa
    Artifact,
    AsciiArmoredDetachedSigningService,
    Content,
    ContentManager,
    ContentArtifact,
    PulpTemporaryFile,
    RemoteArtifact,
    SigningService,
    UnsupportedDigestValidationError,
)
from .generic import GenericRelationModel  # noqa
from .exporter import (  # noqa
    Export,
    ExportedResource,
    Exporter,
    FilesystemExport,
    FilesystemExporter,
    PulpExport,
    PulpExporter,
)
from .importer import (  # noqa
    Import,
    Importer,
    PulpImport,
    PulpImporter,
)
from .publication import (  # noqa
    ContentGuard,
    Distribution,
    Publication,
    PublishedArtifact,
    PublishedMetadata,
    RBACContentGuard,
    ContentRedirectContentGuard,
)
from .repository import (  # noqa
    Remote,
    Repository,
    RepositoryContent,
    RepositoryVersion,
    RepositoryVersionContentDetails,
)

# This can lead to circular imports with a custom user model depending on this very module
# Moved to plugin/models/role.py to avoid the circular import.
# from .role import (  # noqa
#     GroupRole,
#     Role,
#     UserRole,
# )

from .status import ContentAppStatus  # noqa

from .task import (  # noqa
    CreatedResource,
    Task,
    TaskGroup,
    Worker,
)
from .upload import (  # noqa
    Upload,
    UploadChunk,
)

# Moved here to avoid a circular import with Task
from .progress import GroupProgressReport, ProgressReport  # noqa


from prometheus_client import Gauge
from prometheus_client.core import GaugeMetricFamily, CounterMetricFamily, REGISTRY


from django.db.models import Sum


class CustomCollector:
    def collect(self):
        yield GaugeMetricFamily(
            'pulp_tasks_running', 'Help text',
            value=Task.objects.filter(state="running").count()
        )

        yield GaugeMetricFamily(
            'pulp_tasks_waiting', 'Help text',
            value=Task.objects.filter(state="waiting").count()
        )

        yield GaugeMetricFamily(
            'pulp_tasks_completed', 'Help text',
            value=Task.objects.filter(state="completed").count()
        )

        yield GaugeMetricFamily(
            'pulp_tasks_failed', 'Help text',
            value=Task.objects.filter(state="failed").count()
        )

        yield GaugeMetricFamily(
            'pulp_tasks_canceled', 'Help text',
            value=Task.objects.filter(state="canceled").count()
        )

        yield GaugeMetricFamily(
            "pulp_workers_online", "Help text",
            value=Worker.objects.online_workers().count()
        )

        yield GaugeMetricFamily(
            "pulp_content_apps_online", "Help text",
            value=ContentAppStatus.objects.online().count()
        )

        c = GaugeMetricFamily("artifact_count_total", 'Help text', labels=['type'])
        c.add_metric(['on_disk'], Artifact.objects.count())
        c.add_metric(['remote'], RemoteArtifact.objects.count())

        yield c

        c = GaugeMetricFamily("artifact_size_total", 'Help text', labels=['type'])
        c.add_metric(['on_disk'], Artifact.objects.aggregate(Sum('size'))['size__sum'] or 0)
        c.add_metric(['remote'], RemoteArtifact.objects.aggregate(Sum('size'))['size__sum'] or 0)

        yield c

        # c.add_metric(['running'], Task.objects.filter(state="running").count())
        # c.add_metric(['waiting'], Task.objects.filter(state="waiting").count())
        # c.add_metric(['failed'], Task.objects.filter(state="failed").count())
        # c.add_metric(['completed'], Task.objects.filter(state="completed").count())
        # c.add_metric(['canceled'], Task.objects.filter(state="canceled").count())

REGISTRY.register(CustomCollector())

