"""
Documentation-only serializers.

Several views in :mod:`api.views` build their JSON responses by hand
(``Response({"message": ...})``) instead of returning a serializer. Those
shapes are invisible to drf-spectacular, so the schema generator would render
them as "No response body".

The serializers below exist purely to describe those payloads to
drf-spectacular via ``@extend_schema``. They are never used to validate or
render real traffic, so changing a view's response means updating the matching
serializer here too.
"""

from rest_framework import serializers

from .serial import UserSerializer


# --------------------------------------------------------------------------- #
# Generic envelopes
# --------------------------------------------------------------------------- #

class MessageResponseSerializer(serializers.Serializer):
    """A single human readable ``message``."""

    message = serializers.CharField()


class DetailResponseSerializer(serializers.Serializer):
    """A single human readable ``detail`` (DRF's own error convention)."""

    detail = serializers.CharField()


class SuccessResponseSerializer(serializers.Serializer):
    """An operation outcome flag with an optional message."""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False)


class ErrorResponseSerializer(serializers.Serializer):
    """Field-name -> list of error strings, as returned by serializer validation."""

    def to_representation(self, instance):  # pragma: no cover - docs only
        return instance


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text='The account email address.')
    password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        help_text='The account password.',
    )


class LoginResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    username = serializers.CharField()
    role = serializers.CharField(help_text='One of: child, Member, Father, Mother, President, Vice President, admin.')
    is_superuser = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    access = serializers.CharField(help_text='JWT access token. Valid for 10 minutes.')
    refresh = serializers.CharField(help_text='JWT refresh token. Valid for 1 day and rotated on use.')


class ResetPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text='Email of the account to reset.')
    new_password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'},
        help_text='Must match new_password.',
    )


# --------------------------------------------------------------------------- #
# Membership requests
# --------------------------------------------------------------------------- #

class ApprovedUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    new_role = serializers.CharField(help_text='Always "Member" after a successful approval.')


class ApproveMembershipResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    user = ApprovedUserSerializer()


class TotalRequestsSerializer(serializers.Serializer):
    total_requests = serializers.IntegerField(help_text='Number of membership requests still pending.')


# --------------------------------------------------------------------------- #
# Users
# --------------------------------------------------------------------------- #

class ProfilePictureRequestSerializer(serializers.Serializer):
    profile_image = serializers.ImageField(help_text='The new profile picture. Sent as multipart/form-data.')


class ProfilePictureResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = UserSerializer()


# --------------------------------------------------------------------------- #
# Newsletter
# --------------------------------------------------------------------------- #

class NewsletterResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['success', 'error'])
    message = serializers.CharField()
