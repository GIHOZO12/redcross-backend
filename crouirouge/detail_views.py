"""Detail pages for fellowships, Red Cross activities and family activities.

The listing endpoints return a truncated card's worth of data and, for
fellowships and Red Cross activities, no id at all - so nothing could link to a
single item. These give each one an address of its own, carrying the full
description, and for a fellowship the gallery of extra images behind it.

Reads are public: the listings they are reached from are public too.

Writes are not. Uploading to the gallery requires a committee officer or staff.
Note this is deliberately a wider rule than the one in family_admin.py, which
is office-only: restructuring families is a governance act, whereas posting
photos of what a fellowship covered is ordinary admin work.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import FamilyActivities, FellowshipImage, Fellowership, RedcrossActivities

OFFICER_ROLES = {"President", "Vice President", "Secretary"}

UNAUTHENTICATED = {"status": False, "message": "You must be logged in to do this"}
NOT_PERMITTED = {
    "status": False,
    "message": "Only committee officers or staff can change fellowship images",
}


def _may_edit_gallery(user):
    if user is None or not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser or user.role in OFFICER_ROLES


def gallery_editor_required(view):
    from functools import wraps

    from .views import _request_user

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _request_user(request)
        if user is None:
            return JsonResponse(UNAUTHENTICATED, status=401)
        if not _may_edit_gallery(user):
            return JsonResponse(NOT_PERMITTED, status=403)
        request.editor = user
        return view(request, *args, **kwargs)

    return wrapper


def _image_url(request, field):
    """Absolute URL for an image field, or None.

    R2 already hands back an absolute URL and build_absolute_uri leaves those
    untouched, so this works on both object storage and local files.
    """
    if not field:
        return None
    try:
        return request.build_absolute_uri(field.url)
    except Exception:
        return None


def _gallery(request, fellowship):
    return [
        {
            "id": img.id,
            "image": _image_url(request, img.image),
            "caption": img.caption,
        }
        for img in fellowship.gallery.all()
    ]


# --------------------------------------------------------------------------- #
# Public detail reads
# --------------------------------------------------------------------------- #


def fellowship_detail(request, id):
    fellowship = get_object_or_404(Fellowership, id=id)
    return JsonResponse(
        {
            "status": True,
            "fellowship": {
                "id": fellowship.id,
                "title": fellowship.title,
                "description": fellowship.description,
                "fellowship_image": _image_url(request, fellowship.fellowership_image),
                "created_at": fellowship.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "gallery": _gallery(request, fellowship),
            },
        }
    )


def redcross_activity_detail(request, id):
    activity = get_object_or_404(RedcrossActivities, id=id)
    return JsonResponse(
        {
            "status": True,
            "activity": {
                "id": activity.id,
                "title": activity.title,
                "description": activity.description,
                "redcross_activities_image": _image_url(
                    request, activity.redcross_activities_image
                ),
                "created_at": activity.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
    )


def family_activity_detail(request, id):
    activity = get_object_or_404(
        FamilyActivities.objects.select_related("family"), id=id
    )
    return JsonResponse(
        {
            "status": True,
            "activity": {
                "id": activity.id,
                "title": activity.title,
                "text": activity.text,
                "activityImage": _image_url(request, activity.activityImage),
                "created": activity.created.strftime("%Y-%m-%d %H:%M:%S"),
                "family": activity.family.name,
            },
        }
    )


# --------------------------------------------------------------------------- #
# Gallery writes
# --------------------------------------------------------------------------- #


@csrf_exempt
@gallery_editor_required
def add_fellowship_image(request, id):
    """Attach one captioned image to a fellowship.

    Multipart: `image` (required), `caption` (optional).
    """
    if request.method != "POST":
        return JsonResponse(
            {"status": False, "message": "Invalid request method"}, status=405
        )

    fellowship = get_object_or_404(Fellowership, id=id)
    image = request.FILES.get("image")
    if not image:
        return JsonResponse(
            {"status": False, "message": "Choose an image to upload"}, status=400
        )

    entry = FellowshipImage.objects.create(
        fellowship=fellowship,
        image=image,
        caption=(request.POST.get("caption") or "").strip(),
    )
    return JsonResponse(
        {
            "status": True,
            "message": "Image added to %s" % fellowship.title,
            "image": {
                "id": entry.id,
                "image": _image_url(request, entry.image),
                "caption": entry.caption,
            },
        },
        status=201,
    )


@csrf_exempt
@gallery_editor_required
def delete_fellowship_image(request, id):
    """Remove one gallery image, and its file from storage."""
    if request.method != "DELETE":
        return JsonResponse(
            {"status": False, "message": "Invalid request method"}, status=405
        )

    entry = get_object_or_404(FellowshipImage, id=id)
    # Delete the stored object too, or the bucket fills with orphans that
    # nothing references. save=False because the row goes next anyway.
    if entry.image:
        entry.image.delete(save=False)
    entry.delete()
    return JsonResponse({"status": True, "message": "Image removed"})
