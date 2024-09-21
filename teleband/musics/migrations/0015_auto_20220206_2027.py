# Generated by Django 3.2.11 on 2022-02-07 01:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("musics", "0014_alter_piece_slug"),
    ]

    operations = [
        migrations.AddField(
            model_name="part",
            name="sample_audio",
            field=models.FileField(blank=True, upload_to="sample_audio/"),
        ),
        migrations.AddField(
            model_name="piece",
            name="accompaniment",
            field=models.FileField(blank=True, upload_to="accompaniments/"),
        ),
    ]
