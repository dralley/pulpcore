import os
from gettext import gettext as _

from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from pulpcore.app import models, settings
from pulpcore.app.serializers import (
    DetailIdentityField,
    ImportIdentityField,
    ModelSerializer,
    RelatedField,
)


class ImporterSerializer(ModelSerializer):
    """Base serializer for Importers."""

    pulp_href = DetailIdentityField(view_name_pattern=r"importer(-.*/.*)-detail",)
    name = serializers.CharField(
        help_text=_("Unique name of the Importer."),
        validators=[UniqueValidator(queryset=models.Importer.objects.all())],
    )

    class Meta:
        model = models.Importer
        fields = ModelSerializer.Meta.fields + ("name",)


class ImportSerializer(ModelSerializer):
    """Serializer for Imports."""

    pulp_href = ImportIdentityField()

    task = RelatedField(
        help_text=_("A URI of the Task that ran the Import."),
        queryset=models.Task.objects.all(),
        view_name="tasks-detail",
    )

    params = serializers.JSONField(
        help_text=_("Any parameters that were used to create the import."),
    )

    class Meta:
        model = models.Importer
        fields = ModelSerializer.Meta.fields + ("task", "params")


class PulpImporterSerializer(ImporterSerializer):
    """Serializer for PulpImporters."""

    repo_mapping = serializers.DictField(
        child=serializers.CharField(),
        help_text=_(
            "Mapping of repo names in an export file to the repo names in Pulp. "
            "For example, if the export has a repo named 'foo' and the repo to "
            "import content into was 'bar', the mapping would be \"{'foo': 'bar'}\"."
        ),
        required=False,
    )

    def create(self, validated_data):
        """
        Save the PulpImporter and handle saving repo mapping.

        Args:
            validated_data (dict): A dict of validated data to create the PulpImporter

        Raises:
            ValidationError: When there's a problem with the repo mapping.

        Returns:
            PulpImporter: the created PulpImporter
        """
        repo_mapping = validated_data.pop("repo_mapping", {})
        importer = super().create(validated_data)
        try:
            importer.repo_mapping = repo_mapping
        except Exception as err:
            importer.delete()
            raise serializers.ValidationError(_("Bad repo mapping: {}").format(err))
        else:
            return importer

    class Meta:
        model = models.PulpImporter
        fields = ImporterSerializer.Meta.fields + ("repo_mapping",)


class PulpImportSerializer(ModelSerializer):
    """Serializer for call to import into Pulp."""

    path = serializers.CharField(
        help_text=_("Path to export that will be imported."), required=False
    )
    toc = serializers.CharField(
        help_text=_(
            "Path to a table-of-contents file describing chunks to be validated, "
            + "reassembled, and imported."
        ),
        required=False,
    )

    def _check_path_allowed(self, param, a_path):
        user_provided_realpath = os.path.realpath(a_path)
        for allowed_path in settings.ALLOWED_IMPORT_PATHS:
            if user_provided_realpath.startswith(allowed_path):
                return user_provided_realpath

        raise serializers.ValidationError(
            _("{} '{}' is not an allowed import path").format(param, a_path)
        )

    def validate_path(self, value):
        """
        Check if path exists and is in ALLOWED_IMPORT_PATHS.

        Args:
            value (str): The user-provided value path to be validated.

        Raises:
            ValidationError: When path is not in the ALLOWED_IMPORT_PATHS setting.

        Returns:
            The validated value.
        """
        return self._check_path_allowed("path", value)

    def validate_toc(self, value):
        """
        Check validity of provided 'toc' parameter.

        'toc' must:
          * be within ALLOWED_IMPORT_PATHS.
          * be valid JSON
          * point to chunked-export-files that exist 'next to' the 'toc' file

        NOTE: this method does NOT validate checksums of the chunked-export-files. That
        happens asynchronously, due to time/responsiveness constraints.

        Args:
            value (str): The user-provided toc-file-path to be validated.

        Raises:
            ValidationError: When toc is not in the ALLOWED_IMPORT_PATHS setting,
            toc is not a valid JSON table-of-contents file, or when toc points to
            chunked-export-files that can't be found in the same directory as the toc-file.

        Returns:
            The validated value.
        """

        return self._check_path_allowed("toc", value)

    def validate(self, data):
        # only one-of 'path'/'toc'
        if data.get("path", None) and data.get("toc", None):
            raise serializers.ValidationError(_("Only one of 'path' and 'toc' may be specified."))

        # requires one-of 'path'/'toc'
        if not data.get("path", None) and not data.get("toc", None):
            raise serializers.ValidationError(_("One of 'path' or 'toc' must be specified."))

        return super().validate(data)

    class Meta:
        model = models.Import
        fields = (
            "path",
            "toc",
        )