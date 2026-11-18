"""Family administration for the committee: President, Vice President, Secretary.

These let an officer run the family structure from the admin dashboard without
going through Django admin: see a family's parents and children, assign a
father or mother, and add a child.

Unlike the other admin endpoints in this project, every view here checks who is
calling. They change membership, so leaving them open would let anyone on the
internet reassign a family's parents.

Roles are left alone. A person's `role` is their committee office - President,
Vice President, Secretary, Member - and where they sit in a family is a
separate thing, held by `Family.father`/`mother` and by `Members` rows. One
person can be a child in one family, a father in another, and President of the
unit, and overwriting `role` on assignment would destroy two of those three.

The one structural rule is that `father` and `mother` are OneToOne, so nobody
parents more than one family; everything else may overlap.
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
    """True when this user holds one of the committee offices.

    Deliberately role-only: `is_staff` is a Django permission flag that gets
    ticked for all sorts of reasons, and someone who can reach the admin
    dashboard is not thereby entitled to restructure families. A superuser who
    needs to do this either takes an office or uses Django admin, where they
    can already edit Family and Members directly.
    """
    if user is None or not user.is_authenticated:
        return False
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
    """Accounts an officer can pick from, with every placement each one holds.

    Everyone is listed rather than filtered by role, because a person's role is
    their committee office and says nothing about where they sit in a family.

    `placements` is a list, not one value: the same person can be a child in
    one family and a father in another, and the officer needs to see both
    before deciding. `is_parent_elsewhere` is the only hard blocker - father
    and mother are OneToOne, so nobody can parent two families.
    """
    users = User.objects.all().order_by("username")

    placements = {}

    def add(user_id, family_name, kind):
        if user_id:
            placements.setdefault(user_id, []).append(
                {"family": family_name, "as": kind}
            )

    for fam in Family.objects.all().select_related("father", "mother"):
        add(fam.father_id, fam.name, "father")
        add(fam.mother_id, fam.name, "mother")
    for member in Members.objects.exclude(user=None).select_related("family"):
        add(member.user_id, member.family.name, "child")

    def brief(u):
        held = placements.get(u.id, [])
        return dict(
            _user_brief(u),
            placements=held,
            is_parent_elsewhere=any(p["as"] in ("father", "mother") for p in held),
        )

    return JsonResponse({"status": True, "users": [brief(u) for u in users]})


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

    # `user.role` is left untouched on purpose - it records their committee
    # office, not their place in a family. Overwriting it here would strip a
    # President of that office just because they took over a family.

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
        # Role untouched: being a child of a family says nothing about the
        # office they hold, and they may well parent a different family.
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


@csrf_exempt
@officer_required
def remove_child(request, id):
    """Take a child out of a family.

    Deletes the Members row that places them, nothing else. The person's
    account is untouched: they keep their login, their committee office and
    any other placement they hold, and can be added to a family again. A
    child recorded without an account simply disappears, since the row was
    the whole record of them.
    """
    if request.method != "DELETE":
        return JsonResponse(
            {"status": False, "message": "Invalid request method"}, status=405
        )

    member = get_object_or_404(Members.objects.select_related("family", "user"), id=id)
    who = member.user.username if member.user else (
        ("%s %s" % (member.first_name, member.last_name)).strip() or "Child"
    )
    family_name = member.family.name
    member.delete()

    return JsonResponse(
        {
            "status": True,
            "message": "%s removed from %s" % (who, family_name),
        }
    )
