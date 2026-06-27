from django.db import models

from teleband.instruments.models import Transposition
from teleband.utils.fields import generate_slug_from_name


class EnsembleType(models.Model):

    name = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Ensemble Type"
        verbose_name_plural = "Ensemble Types"

    def __str__(self):
        return self.name


class Composer(models.Model):

    name = models.CharField(max_length=255)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class Piece(models.Model):

    name = models.CharField(max_length=255)
    slug = models.SlugField()
    composer = models.ForeignKey(Composer, null=True, on_delete=models.PROTECT)
    video = models.URLField(blank=True)
    audio = models.URLField(blank=True)
    date_composed = models.DateField(null=True, blank=True)
    ensemble_type = models.ForeignKey(EnsembleType, on_delete=models.PROTECT)
    accompaniment = models.FileField(blank=True, upload_to="accompaniments/")

    def save(self, *args, **kwargs):
        if not self.pk:
            generate_slug_from_name(self, Piece)

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PartType(models.Model):

    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Part(models.Model):

    name = models.CharField(max_length=255)
    part_type = models.ForeignKey(PartType, on_delete=models.PROTECT)
    piece = models.ForeignKey(Piece, related_name="parts", on_delete=models.PROTECT)
    sample_audio = models.FileField(blank=True, upload_to="sample_audio/")
    chord_scale_pattern = models.JSONField(blank=True, null=True)

    def for_activity(activity, piece):
        # Get this piece's part for this kind of activity, falling back to the
        # piece's Melody part. A single get() with a DoesNotExist fallback
        # replaces the old exists()+get() double query.
        if activity.part_type:
            try:
                return Part.objects.get(piece=piece, part_type=activity.part_type)
            except Part.DoesNotExist:
                pass
        return Part.objects.get(
            piece=piece, part_type=PartType.objects.get(name="Melody")
        )

    def __str__(self):
        return self.name


class PartTransposition(models.Model):

    part = models.ForeignKey(
        Part, related_name="transpositions", on_delete=models.PROTECT
    )
    transposition = models.ForeignKey(Transposition, on_delete=models.PROTECT)
    flatio = models.TextField(null=True, blank=True)

    class Meta:
        verbose_name = "Part Transposition"
        verbose_name_plural = "Part Transpositions"

    def __str__(self):
        return f"{self.part.piece}: {self.part} [{self.transposition}]"


class PartInstrumentSample(models.Model):
    part = models.ForeignKey(
        Part, related_name="instrument_samples", on_delete=models.PROTECT
    )
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    sample_audio = models.FileField(upload_to="instrument_samples/")

    class Meta:
        unique_together = ["part", "instrument"]
        verbose_name = "Part Instrument Sample"
        verbose_name_plural = "Part Instrument Samples"

    def __str__(self):
        return f"{self.part} - {self.instrument} Sample"
