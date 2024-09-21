# Generated by Django 3.2.11 on 2022-01-30 01:55

from django.db import migrations

from teleband.utils.fields import generate_slug_from_name


def update_site_forward(apps, schema_editor):
    """Compute slugs from names."""
    Piece = apps.get_model("musics", "Piece")
    for piece in Piece.objects.all():
        generate_slug_from_name(piece, Piece)
        piece.save()


class Migration(migrations.Migration):

    dependencies = [
        ("musics", "0012_piece_slug"),
    ]

    operations = [migrations.RunPython(update_site_forward, migrations.RunPython.noop)]
