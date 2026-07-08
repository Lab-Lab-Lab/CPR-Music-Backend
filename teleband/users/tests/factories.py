from typing import Any, Sequence

from django.contrib.auth import get_user_model
from factory import Faker, post_generation
from factory import Sequence as FactorySequence
from factory.django import DjangoModelFactory

from teleband.users.models import Role


class RoleFactory(DjangoModelFactory):

    name = Faker("color")

    class Meta:
        model = Role


class UserFactory(DjangoModelFactory):

    # Sequence (not Faker("user_name")) so the default username is guaranteed
    # unique: Faker usernames repeat, and with django_get_or_create a repeat
    # returns an existing user who then collides on UNIQUE(user, course) when
    # enrolled again. An explicit username= still dedupes via get_or_create.
    username = FactorySequence(lambda n: f"factory-user-{n}")
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)

    class Meta:
        model = get_user_model()
        django_get_or_create = ["username"]
