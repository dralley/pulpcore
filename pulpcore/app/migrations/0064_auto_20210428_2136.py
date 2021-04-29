# Generated by Django 2.2.20 on 2021-04-28 21:36

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django_lifecycle.mixins
import pulpcore.app.models.content
import pulpcore.app.models.fields
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0063_repository_retained_versions'),
    ]

    operations = [
        migrations.CreateModel(
            name='RemoteSource',
            fields=[
                ('pulp_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('pulp_created', models.DateTimeField(auto_now_add=True)),
                ('pulp_last_updated', models.DateTimeField(auto_now=True, null=True)),
                ('url', models.TextField(validators=[django.core.validators.URLValidator])),
            ],
            bases=(django_lifecycle.mixins.LifecycleModelMixin, models.Model),
        ),
        migrations.AlterUniqueTogether(
            name='remoteartifact',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='remoteartifact',
            name='content_artifact',
        ),
        migrations.RemoveField(
            model_name='remoteartifact',
            name='remote',
        ),
        migrations.AlterField(
            model_name='artifact',
            name='file',
            field=pulpcore.app.models.fields.ArtifactFileField(max_length=255, null=True, upload_to=pulpcore.app.models.content.Artifact.storage_path),
        ),
        migrations.AlterField(
            model_name='artifact',
            name='sha256',
            field=models.CharField(db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='artifact',
            name='size',
            field=models.BigIntegerField(null=True),
        ),
        migrations.AlterField(
            model_name='contentartifact',
            name='artifact',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='content_memberships', to='core.Artifact'),
        ),
        migrations.AddConstraint(
            model_name='artifact',
            constraint=models.CheckConstraint(check=models.Q(models.Q(models.Q(_negated=True, file__exact=''), ('sha256__isnull', False), ('size__isnull', False)), ('file__exact', ''), _connector='OR'), name='non_downloaded_artifact_remote_sources'),
        ),
        migrations.DeleteModel(
            name='RemoteArtifact',
        ),
        migrations.AddField(
            model_name='remotesource',
            name='artifact',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='remote_sources', to='core.Artifact'),
        ),
        migrations.AddField(
            model_name='remotesource',
            name='remote',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.Remote'),
        ),
        migrations.AlterUniqueTogether(
            name='remotesource',
            unique_together={('remote', 'artifact')},
        ),
    ]
