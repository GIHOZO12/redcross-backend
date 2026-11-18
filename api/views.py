from io import BytesIO
import os
from django.http import JsonResponse
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.uploads import DrainsUploadBeforeAuthMixin, drains_upload_before_auth
from reportlab.lib.pagesizes import letter
from rest_framework.permissions import IsAdminUser
from rest_framework.views import APIView
from reportlab.lib.utils import ImageReader
from io import BytesIO
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework import generics,permissions

from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from django.utils.decorators import method_decorator

from django.http import HttpResponse
from reportlab.pdfgen import canvas
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import csrf_exempt,csrf_protect,ensure_csrf_cookie
from django.shortcuts import get_object_or_404
from crouirouge.models import (SubscribeNewslatter, User,Family,Announcement,Members,
                               Fellowership,
                               RedcrossActivities,RequestMembership,
                               FirstAidCourse,Address,BloodDonation,Generalinformation,)
from .serial import (NewsletterSerializer, UserSerializer,FamilySerializer,
                     AnnouncementSerializer,MembersSerializer,
                     Felloweshipserializer,RequestMembershipSerializer,
                     Redcrossactivitiesserializer,
                     FirstAidCourseSerializer,GeneralinformationSerializer)
from rest_framework_simplejwt.views import TokenObtainPairView,TokenRefreshView 
from rest_framework_simplejwt.tokens import RefreshToken 
from .serial import LoginSerializer

# --------------------------------------------------------------------------- #
# OpenAPI schema annotations (drf-spectacular)
# --------------------------------------------------------------------------- #
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiExample,
    OpenApiResponse,
)

from .docs import (
    ApproveMembershipResponseSerializer,
    DetailResponseSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    MessageResponseSerializer,
    NewsletterResponseSerializer,
    ProfilePictureRequestSerializer,
    ProfilePictureResponseSerializer,
    ResetPasswordRequestSerializer,
    SuccessResponseSerializer,
    TotalRequestsSerializer,
)






@extend_schema(
    tags=['Membership Requests'],
    summary='Request membership',
    description=(
        'Submits a request to become a Red Cross member.\n\n'
        'The requesting account is taken from the access token, so a `user` '
        'value in the body is ignored. The request is refused with `400` when '
        'the caller already has a request in `pending` state, or already holds '
        'the `Member` or `admin` role.'
    ),
    request=RequestMembershipSerializer,
    responses={
        201: OpenApiResponse(
            response=DetailResponseSerializer,
            description='Request created.',
            examples=[
                OpenApiExample(
                    'Created',
                    value={'detail': 'Membership request submitted successfully.'},
                ),
            ],
        ),
        400: OpenApiResponse(
            response=DetailResponseSerializer,
            description='Already pending, or the caller is already a member.',
            examples=[
                OpenApiExample(
                    'Pending request exists',
                    value={'detail': 'You already have a pending membership request.'},
                ),
                OpenApiExample(
                    'Already a member',
                    value={'detail': 'You are already a member.'},
                ),
            ],
        ),
    },
)
class RequestMembershipView(generics.CreateAPIView):
    queryset = RequestMembership.objects.all()
    serializer_class = RequestMembershipSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        # Check if user already has a pending request
        if RequestMembership.objects.filter(user=request.user, status='pending').exists():
            return Response(
                {'detail': 'You already have a pending membership request.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if user is already a member
        if request.user.role in ['Member', 'admin']:
            return Response(
                {'detail': 'You are already a member.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            {'detail': 'Membership request submitted successfully.'},
            status=status.HTTP_201_CREATED,
            headers=headers
        )



@extend_schema(
    tags=['Membership Requests'],
    summary='List pending membership requests',
    description='Returns every membership request still in `pending` state.',
    responses={200: RequestMembershipSerializer(many=True)},
)
class Allrequestedmemberships(generics.ListAPIView):
    queryset = RequestMembership.objects.all()
    serializer_class = RequestMembershipSerializer
    permission_classes = [permissions.IsAuthenticated]
    def get_queryset(self):
        return RequestMembership.objects.filter(status='pending')
@extend_schema(
    tags=['Membership Requests'],
    summary='Approve a membership request',
    description=(
        'Approves the membership request identified by `pk`: the request moves '
        'to `approved` and the requesting user is promoted to the `Member` '
        'role. Takes no request body.'
    ),
    request=None,
    responses={
        200: OpenApiResponse(
            response=ApproveMembershipResponseSerializer,
            description='Request approved and the user promoted.',
            examples=[
                OpenApiExample(
                    'Approved',
                    value={
                        'message': 'Request approved successfully.',
                        'user': {'id': 12, 'username': 'jdoe', 'new_role': 'Member'},
                    },
                ),
            ],
        ),
        400: OpenApiResponse(
            response=MessageResponseSerializer,
            description='The request was already approved or rejected.',
        ),
        404: OpenApiResponse(
            response=MessageResponseSerializer,
            description='No membership request with that id.',
        ),
    },
)
class ApproveRequestMembership(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        try:
            request_obj = RequestMembership.objects.get(pk=pk)
            
            if request_obj.status != 'pending':
                return Response(
                    {'message': 'Request has already been processed.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update request status
            request_obj.status = 'approved'
            request_obj.save()
            
            # Update user role
            user = request_obj.user
            user.role = 'Member'
            user.save()
            
            return Response(
                {
                    'message': 'Request approved successfully.',
                    'user': {
                        'id': user.id,
                        'username': user.username,
                        'new_role': user.role
                    }
                },
                status=status.HTTP_200_OK
            )
            
        except ObjectDoesNotExist:
            return Response(
                {'message': 'Request does not exist.'},
                status=status.HTTP_404_NOT_FOUND
            
            
            )
        
@extend_schema(
    tags=['Membership Requests'],
    summary='Count pending membership requests',
    description='Returns the number of membership requests still awaiting review.',
    responses={200: TotalRequestsSerializer},
)
class Totalrequestedmemberships(APIView):
    authentication_classes = [JWTAuthentication]  # Add JWT authentication
    permission_classes = [permissions.IsAuthenticated]
    def get(self, request):
        total_requests = RequestMembership.objects.filter(status='pending').count()
        return Response({'total_requests': total_requests}, status=status.HTTP_200_OK)
    
        
@extend_schema(
    methods=['GET'],
    tags=['Users'],
    summary='List users',
    description='Returns every user account.',
    responses={200: UserSerializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Users'],
    summary='Create a user',
    description=(
        'Creates a user account. `role`, `first_name` and `last_name` are '
        'read-only on this serializer and cannot be set here; new accounts get '
        'the default `child` role.'
    ),
    request=UserSerializer,
    responses={
        201: UserSerializer,
        400: OpenApiResponse(
            description='Validation failed; the body maps field names to lists of error strings.',
        ),
    },
)
@api_view(['GET','POST'])
def user_list(request):
    if request.method == 'GET':
        users = User.objects.all()
        serializer = UserSerializer(users, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
@extend_schema(
    methods=['GET'],
    tags=['Families'],
    summary='List families',
    description=(
        'Returns every family.\n\n'
        'The same view is also routed at `/api/families/{name}/`, but that '
        'variant does not currently return a response - use this collection '
        'endpoint, or `GET /family_list/{name}/` in the site app, instead.'
    ),
    responses={200: FamilySerializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Families'],
    summary='Create a family',
    request=FamilySerializer,
    responses={
        201: FamilySerializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])
def family_list(request,name=None):
    if request.method == 'GET':
        if name is not None: 
            famill=get_object_or_404(Family)
            serializer=FamilySerializer(famill)
        else:    
          family = Family.objects.all()
          serializer = FamilySerializer(family, many=True)
          return Response(serializer.data)
    elif request.method == 'POST':
        serializer = FamilySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
@extend_schema(
    methods=['GET'],
    tags=['Families'],
    summary='List family members',
    description='Returns every family member record.',
    responses={200: MembersSerializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Families'],
    summary='Create a family member',
    description=(
        'Creates a family member record.\n\n'
        'Note: the view compares the request method against the lowercase '
        'string `"post"`, so this branch is currently unreachable and a POST '
        'falls through to an empty response.'
    ),
    request=MembersSerializer,
    responses={
        201: MembersSerializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])
def members_list(request):
    if request.method =="GET":
        member=Members.objects.all()
        serializer=MembersSerializer(member,many=True)
        return Response(serializer.data)
    elif request.method=="post":
        serializer=MembersSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data,201)
        return Response(serializer.errors,401)    
@extend_schema(
    methods=['GET'],
    tags=['Announcements'],
    summary='List announcements',
    responses={200: AnnouncementSerializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Announcements'],
    summary='Create an announcement',
    request=AnnouncementSerializer,
    responses={
        201: AnnouncementSerializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])
def announcement_list(request):
    if request.method == 'GET':
        announcement = Announcement.objects.all()
        serializer = AnnouncementSerializer(announcement, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = AnnouncementSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@extend_schema(
    methods=['GET'],
    tags=['Fellowships'],
    summary='List fellowships',
    responses={200: Felloweshipserializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Fellowships'],
    summary='Create a fellowship',
    description=(
        'Creates a fellowship post. Send as `multipart/form-data` when '
        'including the `fellowership_image` upload.'
    ),
    request={
        'multipart/form-data': Felloweshipserializer,
        'application/json': Felloweshipserializer,
    },
    responses={
        201: Felloweshipserializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])
def felloweship_list(request):
    if request.method == 'GET':
        felloweship = Fellowership.objects.all()
        serializer = Felloweshipserializer(felloweship, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = Felloweshipserializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
@extend_schema(
    methods=['GET'],
    tags=['Red Cross Activities'],
    summary='List Red Cross activities',
    responses={200: Redcrossactivitiesserializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['Red Cross Activities'],
    summary='Create a Red Cross activity',
    description=(
        'Creates an activity post. Send as `multipart/form-data` when '
        'including the `redcross_activities_image` upload.'
    ),
    request={
        'multipart/form-data': Redcrossactivitiesserializer,
        'application/json': Redcrossactivitiesserializer,
    },
    responses={
        201: Redcrossactivitiesserializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])
def redcrossactivities_list(request):
    if request.method == 'GET':
        redcrossactivities = RedcrossActivities.objects.all()
        serializer = Redcrossactivitiesserializer(redcrossactivities, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = Redcrossactivitiesserializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    

@extend_schema(
    methods=['GET'],
    tags=['First Aid Courses'],
    summary='List first aid courses',
    responses={200: FirstAidCourseSerializer(many=True)},
)
@extend_schema(
    methods=['POST'],
    tags=['First Aid Courses'],
    summary='Create a first aid course',
    description=(
        'Creates a course entry. `video_url` links to where the video is '
        'hosted, such as YouTube or Google Drive.'
    ),
    request={
        'multipart/form-data': FirstAidCourseSerializer,
        'application/json': FirstAidCourseSerializer,
    },
    responses={
        201: FirstAidCourseSerializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
)
@api_view(['GET','POST'])

def first_id_course_list(request):
    if request.method == 'GET':
        first_aid_course = FirstAidCourse.objects.all()
        serializer=FirstAidCourseSerializer(first_aid_course,many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = FirstAidCourseSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    


def _token_cookie_seconds(key):
    """Lifetime of a JWT cookie, in seconds, from SIMPLE_JWT.

    Without an explicit max_age, set_cookie writes a *session cookie*, which
    the browser deletes when it closes - so the user would be logged out on
    browser restart no matter how long the token itself is valid for.
    """
    return int(settings.SIMPLE_JWT[key].total_seconds())


def _set_access_cookie(response, access_token):
    response.set_cookie(
        key='access_token', value=access_token, httponly=True, secure=True,
        samesite='None', path='/',
        max_age=_token_cookie_seconds('ACCESS_TOKEN_LIFETIME'))


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        key='refresh_token', value=refresh_token, httponly=True, secure=True,
        samesite='None', path='/',
        max_age=_token_cookie_seconds('REFRESH_TOKEN_LIFETIME'))


class CustomTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        res = Response()
        try:
            response = super().post(request, *args, **kwargs)
            token = response.data
            access_token = token["access"]
            refresh_token = token["refresh"]

            res.data = {"success": True}
            _set_access_cookie(res, access_token)
            _set_refresh_cookie(res, refresh_token)
            return res

        except Exception as e:
            print("Error in CustomTokenObtainPairView:", e)
            res.data = {"success": False}
            return res
  
        
class CustomRefreshToken(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        try:
            refresh_token = request.COOKIES.get("refresh_token")
            print("Received Refresh Token:", refresh_token)
            
            if not refresh_token:
                return Response({"refreshed": False, "message": "No refresh token in cookies"}, status=400)

            request.data['refresh'] = refresh_token
            response = super().post(request, *args, **kwargs)
            token = response.data

            res = Response()
            res.data = {"refreshed": True}
            _set_access_cookie(res, token["access"])

            # ROTATE_REFRESH_TOKENS means this response carries a NEW refresh
            # token and BLACKLIST_AFTER_ROTATION has just invalidated the one
            # sent in. Dropping it left the browser holding a blacklisted
            # token, so the next refresh failed and the user was logged out
            # after two access-token lifetimes however long the refresh token
            # was configured to live.
            if "refresh" in token:
                _set_refresh_cookie(res, token["refresh"])
            return res

        except Exception as e:
            print("Error in CustomRefreshToken:", e)  # Debugging
            return Response({"refreshed": False, "message": str(e)}, status=500)
          
@csrf_exempt          
@extend_schema(
    tags=['Authentication'],
    summary='Clear the auth cookies',
    description=(
        'Deletes the `access_token` and `refresh_token` cookies.\n\n'
        'This does not blacklist the refresh token, so a client that still '
        'holds the token string can keep using it until it expires. Takes no '
        'request body.'
    ),
    request=None,
    responses={
        200: OpenApiResponse(
            response=SuccessResponseSerializer,
            description='Cookies cleared.',
            examples=[OpenApiExample('Cleared', value={'success': True})],
        ),
        500: OpenApiResponse(
            response=SuccessResponseSerializer,
            description='Unexpected failure.',
        ),
    },
    auth=[],
)
@api_view(["POST"])
def logout_view(request):
    try:
        res = Response()    
        res.data={"success":True}
        res.delete_cookie("access_token" ,path="/",samesite="None")
        
        res.delete_cookie("refresh_token" ,path="/",samesite="None")
        return res

    except:
        return Response({"success":False},status=500)
    


@extend_schema(
    tags=['Users'],
    summary='Current user',
    description='Returns the account that owns the credentials used for this request.',
    responses={200: UserSerializer},
)
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    user = request.user
    serializer = UserSerializer(user)
    return Response(serializer.data)


from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

@extend_schema(
    tags=['Users'],
    summary='Update the current user',
    description=(
        'Partially updates the authenticated user - omitted fields keep their '
        'current values. Only `username`, `email`, `password` and '
        '`profile_image` are writable on this serializer.\n\n'
        'This endpoint accepts a JWT bearer token only; session and basic auth '
        'are not enabled on it.'
    ),
    request=UserSerializer,
    responses={
        200: UserSerializer,
        400: OpenApiResponse(description='Validation failed.'),
        404: OpenApiResponse(description='User not found.'),
    },
)
@drains_upload_before_auth
@api_view(['POST'])
@authentication_classes([JWTAuthentication])  # Use JWT authentication
@permission_classes([IsAuthenticated])  # Require authenticated users
def add_user_info(request):
    print(request.data)  # Log incoming data
    try:
        # Fetch the existing user instance
        user = request.user  # Get the authenticated user
    except User.DoesNotExist:
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    # Use partial=True to allow partial updates
    serializer = UserSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
    print(serializer.errors)  # Log validation errors
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)





@extend_schema(
    tags=['Authentication'],
    summary='Register a new account',
    description=(
        'Creates a user account. Open to anonymous callers.\n\n'
        '`email` and `username` must both be unique. New accounts receive the '
        'default `child` role - promotion to `Member` happens through the '
        'membership request workflow.'
    ),
    responses={
        201: UserSerializer,
        400: OpenApiResponse(
            description='Validation failed, e.g. the email is already registered.',
        ),
    },
    auth=[],
)
class Createuserview(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny]
    # Public endpoint: authenticate nobody. Without this, a browser that
    # also holds a Django session is authenticated by SessionAuthentication,
    # which then enforces CSRF and rejects the call with 403 CSRF Failed.
    authentication_classes = []

@method_decorator(csrf_exempt, name='dispatch')
@extend_schema(
    tags=['Authentication'],
    summary='Log in',
    description=(
        'Exchanges an email and password for a JWT `access` / `refresh` pair, '
        'together with the profile fields the frontend needs in order to pick '
        'a landing page.\n\n'
        'Send the access token on later requests as '
        '`Authorization: Bearer <access>`.'
    ),
    request=LoginRequestSerializer,
    responses={
        200: OpenApiResponse(
            response=LoginResponseSerializer,
            description='Login successful.',
            examples=[
                OpenApiExample(
                    'Success',
                    value={
                        'message': 'Login successful',
                        'username': 'jdoe',
                        'role': 'Member',
                        'is_superuser': False,
                        'is_staff': False,
                        'access': 'eyJhbGciOiJIUzI1NiIsInR5cCI6...',
                        'refresh': 'eyJhbGciOiJIUzI1NiIsInR5cCI6...',
                    },
                ),
            ],
        ),
        401: OpenApiResponse(
            response=MessageResponseSerializer,
            description='Wrong password.',
            examples=[OpenApiExample('Invalid', value={'message': 'Invalid credentials'})],
        ),
        404: OpenApiResponse(
            response=MessageResponseSerializer,
            description='No account with that email.',
            examples=[OpenApiExample('Unknown email', value={'message': 'User not found'})],
        ),
    },
    auth=[],
)
class LoginView(APIView):
    permission_classes = [AllowAny]
    # Public endpoint: authenticate nobody. Without this, a browser that
    # also holds a Django session is authenticated by SessionAuthentication,
    # which then enforces CSRF and rejects the call with 403 CSRF Failed.
    authentication_classes = []

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        try:
            user = User.objects.get(email=email)  # Find user by email
            user = authenticate(email=user.email, password=password)

            if user:
                refresh = RefreshToken.for_user(user)
                return Response({
                    "message": "Login successful",
                    "username": user.username,
                    "role": user.role,
                    "is_superuser": user.is_superuser,
                    "is_staff": user.is_staff,
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                }, status=status.HTTP_200_OK)
            return Response({"message": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED)
        except User.DoesNotExist:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)



@extend_schema(
    tags=['Authentication'],
    summary='Reset a password',
    description=(
        'Sets a new password for the account with the given email.\n\n'
        'Note: this endpoint is open to anonymous callers and does not verify '
        'ownership of the address through an emailed token, so anyone who '
        'knows a registered email address can change that password.'
    ),
    request=ResetPasswordRequestSerializer,
    responses={
        200: OpenApiResponse(
            response=MessageResponseSerializer,
            description='Password changed.',
            examples=[OpenApiExample('Success', value={'message': 'Password reset successful'})],
        ),
        400: OpenApiResponse(
            response=MessageResponseSerializer,
            description='new_password and confirm_password do not match.',
        ),
        404: OpenApiResponse(
            response=MessageResponseSerializer,
            description='No account with that email.',
        ),
    },
    auth=[],
)
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]
    # Public endpoint: authenticate nobody. Without this, a browser that
    # also holds a Django session is authenticated by SessionAuthentication,
    # which then enforces CSRF and rejects the call with 403 CSRF Failed.
    authentication_classes = []
    def post(self, request):
        email = request.data.get("email")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")
        if new_password != confirm_password:
            return Response({"message": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(email__exact=email)
            user.set_password(new_password)
            user.save()
            return Response({"message": "Password reset successful"}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"message": "User not found"}, status=status.HTTP_404_NOT_FOUND)


        


        
@method_decorator(csrf_exempt, name='dispatch')
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]  # Ensure only authenticated users can access this endpoint

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if not refresh_token:
                return Response({"success": False, "message": "No refresh token found."}, status=status.HTTP_400_BAD_REQUEST)

            # Verify the refresh token
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()  # Blacklist the refresh token
            except Exception as e:
                return Response({"success": False, "message": "Invalid or expired refresh token."}, status=status.HTTP_400_BAD_REQUEST)

            return Response({"success": True, "message": "Logged out successfully."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"success": False, "message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
@extend_schema(
    tags=['Users'],
    summary='Change the profile picture',
    description=(
        'Replaces the profile picture of the authenticated user. The body must '
        'be `multipart/form-data` with a single `profile_image` file part.'
    ),
    request={'multipart/form-data': ProfilePictureRequestSerializer},
    responses={
        200: ProfilePictureResponseSerializer,
        400: OpenApiResponse(
            response=SuccessResponseSerializer,
            description='The upload failed validation; `errors` carries the details.',
        ),
    },
)
class ChangeProfilePictureView(DrainsUploadBeforeAuthMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        user = request.user
        serializer = UserSerializer(user, data=request.data, partial=True, context={'request': request})

        if serializer.is_valid():
            serializer.save()
            return Response({"success": True, "message": "Profile picture updated successfully", "data": serializer.data})
        else:
            return Response({"success": False, "message": "Failed to update profile picture", "errors": serializer.errors}, status=400)
    






@extend_schema(
    tags=['General Information'],
    summary='Submit general information',
    description=(
        'Creates a member registration record together with its nested '
        '`address` and `blood_donated` objects in a single request. Both '
        'nested objects are required.\n\n'
        '`nationalId` is unique across records, and each user can only have '
        'one general-information record.'
    ),
    request=GeneralinformationSerializer,
    responses={
        201: GeneralinformationSerializer,
        400: OpenApiResponse(description='Validation failed.'),
    },
    auth=[],
)
class GeneralInformation(APIView):
    permission_classes = [AllowAny]
    # Public endpoint: authenticate nobody. Without this, a browser that
    # also holds a Django session is authenticated by SessionAuthentication,
    # which then enforces CSRF and rejects the call with 403 CSRF Failed.
    authentication_classes = []
    def post(self,request,*args,**kwargs):
        serializer=GeneralinformationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data,status=status.HTTP_201_CREATED)
        return Response(serializer.errors,status=status.HTTP_400_BAD_REQUEST)



@extend_schema_view(
    get=extend_schema(
        tags=['General Information'],
        summary='Retrieve general information by user',
        description='Returns the general-information record belonging to `user_id`.',
        responses={
            200: GeneralinformationSerializer,
            404: OpenApiResponse(
                response=DetailResponseSerializer,
                description='No record for that user.',
            ),
        },
    ),
    put=extend_schema(
        tags=['General Information'],
        summary='Update general information by user',
        description=(
            'Updates the record belonging to `user_id`. The update is partial, '
            'so omitted fields keep their current values; the nested `address` '
            'and `blood_donated` objects are updated in place rather than '
            'replaced.'
        ),
        request=GeneralinformationSerializer,
        responses={
            200: GeneralinformationSerializer,
            400: OpenApiResponse(description='Validation failed.'),
            404: OpenApiResponse(
                response=DetailResponseSerializer,
                description='No record for that user.',
            ),
        },
    ),
)
class EditGeneralInformation(APIView):
    permission_classes = [IsAuthenticated]
    def get_object(self, user_id):
        try:
            return Generalinformation.objects.get(user_id=user_id)
        except Generalinformation.DoesNotExist:
            return None

    def get(self, request, user_id, *args, **kwargs):
        general_info = self.get_object(user_id)
        if general_info is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)


        serializer = GeneralinformationSerializer(general_info)
        return Response(serializer.data)
    def put(self, request, user_id, *args, **kwargs):
        general_info = self.get_object(user_id)
        if general_info is None:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = GeneralinformationSerializer(general_info, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




@extend_schema(
    tags=['General Information'],
    summary='Download proof of registration (PDF)',
    description=(
        'Generates a one-page PDF certificate for the member whose '
        'general-information record belongs to `user_id`, and returns it as a '
        'file download (`Content-Disposition: attachment`).'
    ),
    responses={
        (200, 'application/pdf'): OpenApiTypes.BINARY,
        404: OpenApiResponse(
            response=DetailResponseSerializer,
            description='No record for that user.',
        ),
    },
)
class ProofOfRegistrationView(APIView):
    def get(self, request, user_id, *args, **kwargs):
        try:
            # Fetch the user's registration information
            general_info = Generalinformation.objects.get(user_id=user_id)

            # Create a BytesIO buffer to store the PDF
            buffer = BytesIO()

            # Create the PDF object, using the buffer as its "file"
            p = canvas.Canvas(buffer, pagesize=letter)
            p.setTitle("Proof of Registration")
            logo_path = os.path.join(settings.STATIC_ROOT, 'logo.png')  # Path to the logo image
            print("Logo Path:", logo_path)  # Debugging: Print the logo path
            if os.path.exists(logo_path):
                print("Logo exists at:", logo_path)  # Debugging: Confirm the logo exists
                try:
                    logo = ImageReader(logo_path)
                    p.drawImage(logo, 50, 750, width=50, height=50)  # Draw the logo at (50, 750)
                except Exception as e:
                    print("Error loading logo:", e)  # Debugging: Log any errors
            else:
                print("Logo not found at:", logo_path)  # Debugging: Log if the logo is missing

            # Add the text "Nyarugenge Red Cross" next to the logo
            p.setFont("Helvetica-Bold", 16)
            p.drawString(110, 770, "Nyarugenge Red Cross")  # Draw text at (110, 770)

            # Add the title "Proof of Registration"
            p.setFont("Helvetica-Bold", 14)
            p.drawString(100, 720, "Proof of Registration")

            # Add user details to the PDF
            p.setFont("Helvetica", 12)
            p.drawString(100, 690, f"Name: {general_info.user.username}")
            p.drawString(100, 670, f"National ID: {general_info.nationalId}")
            p.drawString(100, 650, f"Department: {general_info.department}")
            p.drawString(100, 630, "Thank you for registering!")

            # Close the PDF object cleanly
            p.showPage()
            p.save()

            # File response with the PDF
            buffer.seek(0)
            response = HttpResponse(buffer, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="proof_of_registration_{user_id}.pdf"'
            return response

        except Generalinformation.DoesNotExist:
            return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    tags=['General Information'],
    summary='List all general information (staff only)',
    description=(
        'Returns the general-information record of every member. Restricted to '
        'staff accounts (`is_staff = true`).'
    ),
    responses={
        200: GeneralinformationSerializer(many=True),
        403: OpenApiResponse(
            response=DetailResponseSerializer,
            description='The caller is not a staff user.',
        ),
    },
)
class Admin_all_generalinformation(APIView):
    permission_classes = [IsAdminUser] 
    def get(self,request,*args,**kwargs):
        general_info=Generalinformation.objects.all()
        serializer=GeneralinformationSerializer(general_info,many=True)
        return Response(serializer.data)
  
@extend_schema(
    tags=['General Information'],
    summary='Download one member record (PDF)',
    description=(
        'Generates a PDF summary of a single general-information record, '
        'including address and blood-donation details.\n\n'
        'Note: `user_id` here is the **general-information record id**, not '
        'the user id - unlike `/api/proof_of_registration/{user_id}/`, which '
        'keys off the user.'
    ),
    responses={
        (200, 'application/pdf'): OpenApiTypes.BINARY,
        404: OpenApiResponse(description='No record with that id.'),
    },
    auth=[],
)
@api_view(['GET'])
@permission_classes([AllowAny])
def download_single_user_info(request, user_id):
    try:
        user = Generalinformation.objects.get(id=user_id)
    except Generalinformation.DoesNotExist:
        return HttpResponse("User not found", status=404)

    # Create a BytesIO buffer to store the PDF
    buffer = BytesIO()

    # Create the PDF object, using the buffer as its "file"
    p = canvas.Canvas(buffer, pagesize=letter)

    # Set the PDF title
    p.setTitle(f"User Information for {user.user.username}")

    # Add the logo and text at the top
    logo_path = os.path.join(settings.STATIC_ROOT,'logo.png')  # Path to the logo image
    if os.path.exists(logo_path):
        logo = ImageReader(logo_path)
        p.drawImage(logo, 50, 750, width=50, height=50)  # Draw the logo at (50, 750)

    # Add the text "Nyarugenge Red Cross" next to the logo
    p.setFont("Helvetica-Bold", 16)
    p.drawString(110, 770, "Nyarugenge Red Cross")  # Draw text at (110, 770)

    # Add user information below the logo and text
    p.setFont("Helvetica", 12)
    p.drawString(100, 700, f"User Information for {user.user.username}")
    p.drawString(100, 680, f"ID: {user.id}")
    p.drawString(100, 660, f"Username: {user.user.username}")
    p.drawString(100, 640, f"Gender: {user.gender}")
    p.drawString(100, 620, f"National ID: {user.nationalId}")
    p.drawString(100, 600, f"Department: {user.department}")
    p.drawString(100, 580, f"Province: {user.address.province}")
    p.drawString(100, 560, f"District: {user.address.district}")
    p.drawString(100, 540, f"Sector: {user.address.sector}")
    p.drawString(100, 520, f"Cell: {user.address.cell}")
    p.drawString(100, 500, f"Village: {user.address.village}")
    p.drawString(100, 480, f"Blood Donated: {user.blood_donated.donated}")
    p.drawString(100, 460, f"Donated Times: {user.blood_donated.donated_times}")

    # Close the PDF object cleanly
    p.showPage()
    p.save()

    # File response with the PDF
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="user_{user.id}_info.pdf"'
    return response






from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

@extend_schema(
    tags=['Newsletter'],
    summary='Send the newsletter',
    description=(
        'Sends an HTML email to every address in the newsletter subscriber '
        'list. When `plain_content` is omitted it is derived from '
        '`html_content` by stripping tags.\n\n'
        'Emails are sent one at a time and synchronously, so the request can '
        'take a while with a large subscriber list.'
    ),
    request=NewsletterSerializer,
    responses={
        200: OpenApiResponse(
            response=NewsletterResponseSerializer,
            description='Newsletter sent.',
            examples=[
                OpenApiExample(
                    'Sent',
                    value={'status': 'success', 'message': 'Newsletter sent to 42 subscribers'},
                ),
            ],
        ),
        400: OpenApiResponse(
            response=NewsletterResponseSerializer,
            description='Validation failed; `message` carries the serializer errors.',
        ),
        500: OpenApiResponse(
            response=NewsletterResponseSerializer,
            description='The mail backend raised an error.',
        ),
    },
)
class SendNewsletterView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = NewsletterSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                {'status': 'error', 'message': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            data = serializer.validated_data
            subscribers = SubscribeNewslatter.objects.all()
            
            for subscriber in subscribers:
                email = EmailMultiAlternatives(
                    data['subject'],
                    data['plain_content'],
                    None,  # Uses DEFAULT_FROM_EMAIL
                    [subscriber.email]
                )
                email.attach_alternative(data['html_content'], "text/html")
                email.send()
            
            return Response({
                'status': 'success',
                'message': f'Newsletter sent to {subscribers.count()} subscribers'
            })
            
        except Exception as e:
            return Response({
                'status': 'error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# --------------------------------------------------------------------------- #
# Documented aliases for simplejwt's token views
# --------------------------------------------------------------------------- #
# simplejwt ships these views unannotated, which lands them in the schema under
# a stray "token" tag with no explanation. Subclassing lets us document them
# without changing any behaviour.

@extend_schema(
    tags=['Authentication'],
    summary='Obtain a JWT token pair',
    description=(
        'Exchanges credentials for an `access` / `refresh` token pair.\n\n'
        'This project sets `USERNAME_FIELD = "email"` on the user model, so the '
        'request body takes `email` and `password` rather than `username`.\n\n'
        'The access token is valid for 10 minutes, the refresh token for 1 day.'
    ),
    auth=[],
)
class DocumentedTokenObtainPairView(TokenObtainPairView):
    """`POST /api/token/` - documented alias of simplejwt's view."""


@extend_schema(
    tags=['Authentication'],
    summary='Refresh a JWT access token',
    description=(
        'Exchanges a valid `refresh` token for a new `access` token.\n\n'
        'Refresh tokens rotate (`ROTATE_REFRESH_TOKENS = True`) and the token '
        'that was sent is blacklisted, so the client must persist the new '
        '`refresh` value returned in the response.'
    ),
    auth=[],
)
class DocumentedTokenRefreshView(TokenRefreshView):
    """`POST /api/token/refresh/` - documented alias of simplejwt's view."""


# --------------------------------------------------------------------------- #
# Health check
# --------------------------------------------------------------------------- #

@extend_schema(
    tags=['Health'],
    summary='Health check',
    description=(
        'Liveness probe for the hosting platform, and a safe target for an '
        'uptime pinger.\n\n'
        'Always returns `200` while the process is answering requests - it '
        'deliberately does not fail when the database is unreachable, because '
        'restarting the web service would not fix that and would only cause a '
        'restart loop. Read `database` in the body to see the real state.\n\n'
        'It does run a `SELECT 1`, which has a useful side effect: pinging this '
        'endpoint keeps a Supabase free-tier project from pausing after 7 days '
        'of inactivity.'
    ),
    responses={
        200: OpenApiResponse(
            description='The process is alive; `database` reports connectivity.',
            examples=[
                OpenApiExample('Healthy', value={'status': 'ok', 'database': 'ok'}),
                OpenApiExample(
                    'Database unreachable',
                    value={'status': 'degraded', 'database': 'error'},
                ),
            ],
        ),
    },
    auth=[],
)
@api_view(['GET'])
@permission_classes([AllowAny])
def healthz(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        database = 'ok'
    except Exception:                                        # noqa: BLE001
        database = 'error'

    return Response({
        'status': 'ok' if database == 'ok' else 'degraded',
        'database': database,
    })
