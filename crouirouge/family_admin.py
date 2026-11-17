"""Family administration for the committee: President, Vice President, Secretary.

These let an officer run the family structure from the admin dashboard without
going through Django admin: see a family's parents and children, assign a
father or mother, and add a child.

Unlike the other admin endpoints in this project, every view here checks who is
calling. They change membership, so leaving them open would let anyone on the
internet reassign a family's parents.

Role is set on assignment. `Family.father`/`mother` carry
`limit_choices_to={'role': 'Father'}`, which only filters Django admin's own
form widget and enforces nothing at the database level, and there is no screen
for editing a user's role. So assigning a user as father sets their role to
Father; otherwise an officer could only ever pick users who happened to already
hold the right role.
"""

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import Family, Members, User

# Committee roles allowed to manage family structure.
OFFICER_ROLES = {"President", "Vice President", "Secretary"}

UNAUTHENTICATED = {"status": False, "message": "You must be logged in to do this"}
NOT_AN_OFFICER = {
    "status": False,
    "message": "Only the President, Vice President or Secretary can manage families",
}


def _is_family_officer(user):
    """True when this user may manage family structure.

    Staff and superusers are included because they already administer every
    family from the same screens.
    """
    if user is None or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return user.role in OFFICER_ROLES


def officer_required(view):
    """Reject anyone who is not a committee officer before the view runs."""
    from functools import wraps

    from .views import _request_user

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = _request_user(request)
        if user is None:
            return JsonResponse(UNAUTHENTICATED, status=401)
        if not _is_family_officer(user):
            return JsonResponse(NOT_AN_OFFICER, status=403)
        request.officer = user
        return view(request, *args, **kwargs)

    return wrapper


def _payload(request):
    """Read a JSON body, falling back to form fields."""
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body or b"{}")
        except ValueError:
            return {}
    return request.POST


def _user_brief(user):
    if user is None:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
    }


def _child_brief(member):
    """A child row, with the account behind it when there is one."""
    return {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
        "user": _user_brief(member.user),
    }


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


@officer_required
def family_overview(request):
    """Every family with its parents and child count."""
    families = (
        Family.objects.all()
        .select_related("father", "mother")
        .prefetch_related("family")
        .order_by("name")
    )
    return JsonResponse(
        {
            "status": True,
            "families": [
                {
                    "id": f.id,
                    "name": f.name,
                    "father": _user_brief(f.father),
                    "mother": _user_brief(f.mother),
                    # `family` is the related_name on Members.family.
                    "children_count": f.family.count(),
                }
                for f in families
            ],
        }
    )


@officer_required
def family_detail(request, id):
    """One family: its parents and every child in it."""
    family = get_object_or_404(
        Family.objects.select_related("father", "mother"), id=id
    )
    children = family.family.select_related("user").order_by("first_name", "last_name")
    return JsonResponse(
        {
            "status": True,
            "family": {
                "id": family.id,
                "name": family.name,
                "father": _user_brief(family.father),
                "mother": _user_brief(family.mother),
                "children": [_child_brief(m) for m in children],
                "children_count": children.count(),
            },
        }
    )


@officer_required
def assignable_users(request):
    """Accounts an officer can pick from, with their current placement.

    Everyone is listed rather than pre-filtered by role, because assigning is
    what sets the role. `family` says where a person already sits so the
    officer can see at a glance that someone is taken.
    """
    users = User.objects.all().order_by("username")
    placements = {}
    for fam in Family.objects.all().select_related("father", "mother"):
        if fam.father_id:
            placements[fam.father_id] = {"family": fam.name, "as": "father"}
        if fam.mother_id:
            placements[fam.mother_id] = {"family": fam.name, "as": "mother"}
    for member in Members.objects.exclude(user=None).select_related("family"):
        placements.setdefault(
            member.user_id, {"family": member.family.name, "as": "child"}
        )

    return JsonResponse(
        {
            "status": True,
            "users": [
                dict(_user_brief(u), placement=placements.get(u.id)) for u in users
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


@csrf_exempt
@officer_required
def assign_parent(request, id):
    """Set a family's father or mother.

    Body: {"user_id": <int>, "parent": "father"|"mother"}
    Passing user_id = null clears the slot.
    """
    if request.method != "POST":
        return JsonResponse(
            {"status": False, "message": "Invalid request method"}, status=405
        )

    family = get_object_or_404(Family, id=id)
    data = _payload(request)
    slot = (data.get("parent") or "").strip().lower()
    if slot not in ("father", "mother"):
        return JsonResponse(
            {"status": False, "message": "parent must be 'father' or 'mother'"},
            status=400,
        )

    raw_id = data.get("user_id")
    if raw_id in (None, "", "null"):
        setattr(family, slot, None)
        family.save()
        return JsonResponse(
            {"status": True, "message": "%s cleared" % slot.capitalize()}
        )

    try:
        user = User.objects.get(id=int(raw_id))
    except (TypeError, ValueError, User.DoesNotExist):
        return JsonResponse({"status": False, "message": "User not found"}, status=404)

    # father/mother are OneToOne, so a person parents exactly one family.
    # Reassigning silently would quietly strip them from the other family, so
    # say where they are and let the officer decide.
    clash = (
        Family.objects.filter(father=user).exclude(id=family.id).first()
        or Family.objects.filter(mother=user).exclude(id=family.id).first()
    )
    if clash:
        return JsonResponse(
            {
                "status": False,
                "message": "%s is already a parent of the %s family. Remove them there first."
                % (user.username, clash.name),
            },
            status=400,
        )

    # A person cannot be both parents of the same family.
    other_slot = "mother" if slot == "father" else "father"
    if getattr(family, other_slot + "_id") == user.id:
        setattr(family, other_slot, None)

    setattr(family, slot, user)
    family.save()

    new_role = "Father" if slot == "father" else "Mother"
    if user.role != new_role:
        user.role = new_role
        user.save(update_fields=["role"])

    return JsonResponse(
        {
            "status": True,
            "message": "%s is now the %s of %s" % (user.username, slot, family.name),
            "family": {
                "id": family.id,
                "father": _user_brief(family.father),
                "mother": _user_brief(family.mother),
            },
        }
    )


@csrf_exempt
@officer_required
def add_child(request, id):
    """Add a child to a family.

    Body: {"user_id": <int>} to attach an existing account, or
          {"first_name", "last_name", "email"} to record a child without one.
    """
    if request.method != "POST":
        return JsonResponse(
            {"status": False, "message": "Invalid request method"}, status=405
        )

    family = get_object_or_404(Family, id=id)
    data = _payload(request)
    raw_id = data.get("user_id")

    if raw_id not in (None, "", "null"):
        try:
            user = User.objects.get(id=int(raw_id))
        except (TypeError, ValueError, User.DoesNotExist):
            return JsonResponse(
                {"status": False, "message": "User not found"}, status=404
            )

        if Members.objects.filter(family=family, user=user).exists():
            return JsonResponse(
                {
                    "status": False,
                    "message": "%s is already a child in this family" % user.username,
                },
                status=400,
            )

        member = Members.objects.create(
            family=family,
            user=user,
            first_name=user.first_name or user.username,
            last_name=user.last_name or "",
            email=user.email,
        )
        if user.role != "child":
            user.role = "child"
            user.save(update_fields=["role"])
    else:
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        email = (data.get("email") or "").strip()
        if not first_name or not last_name or not email:
            return JsonResponse(
                {
                    "status": False,
                    "message": "Pick a user, or give first name, last name and email",
                },
                status=400,
            )
        member = Members.objects.create(
            family=family,
            user=None,
            first_name=first_name,
            last_name=last_name,
            email=email,
        )

    return JsonResponse(
        {
            "status": True,
            "message": "Child added to %s" % family.name,
            "child": _child_brief(member),
        },
        status=201,
    )
