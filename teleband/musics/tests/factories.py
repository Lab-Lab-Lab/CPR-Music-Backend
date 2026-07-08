from factory import Faker, SubFactory
from factory.django import DjangoModelFactory

from teleband.musics.models import Composer, EnsembleType, Part, PartType, Piece


class EnsembleTypeFactory(DjangoModelFactory):

    name = Faker("color")

    class Meta:
        model = EnsembleType


class ComposerFactory(DjangoModelFactory):

    name = Faker("name")

    class Meta:
        model = Composer


class PieceFactory(DjangoModelFactory):

    name = Faker("name")
    ensemble_type = SubFactory(EnsembleTypeFactory)
    composer = SubFactory(ComposerFactory)

    class Meta:
        model = Piece


class PartTypeFactory(DjangoModelFactory):

    name = Faker("word")

    class Meta:
        model = PartType


class PartFactory(DjangoModelFactory):

    name = Faker("word")
    part_type = SubFactory(PartTypeFactory)
    piece = SubFactory(PieceFactory)

    class Meta:
        model = Part
