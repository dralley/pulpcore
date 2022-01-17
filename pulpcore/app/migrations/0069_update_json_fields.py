# Generated by Django 3.2.5 on 2021-07-21 17:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0068_add_timestamp_of_interest'),
    ]

    operations = [
        migrations.AlterField(
            model_name='accesspolicy',
            name='permissions_assignment',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='accesspolicy',
            name='statements',
            field=models.JSONField(),
        ),
        migrations.AlterField(
            model_name='export',
            name='params',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='import',
            name='params',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='pulpexport',
            name='output_file_info',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='pulpexport',
            name='toc_info',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='remote',
            name='headers',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='args',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='error',
            field=models.JSONField(null=True),
        ),
        migrations.AlterField(
            model_name='task',
            name='kwargs',
            field=models.JSONField(null=True),
        ),
    ]