import requests
import requests_unixsocket
import json

from typing import Optional

from django.db import models
from django.contrib.auth.models import AbstractBaseUser
from django.http.request import HttpRequest

from rest_framework.authentication import get_authorization_header, BasicAuthentication
from rest_framework import HTTP_HEADER_ENCODING
from rest_framework.request import Request

from common_module.authentication import ThirdPartyAuthentication
from common_module.mixins import MockRequest

# Create your models here.


class Consumer(models.Model):
    user_id = models.IntegerField()
    apikey = models.CharField(max_length=32)

    def __unicode__(self):
        return self.user_id

    def __str__(self):
        return self.user_id


class Upstream(models.Model):
    host = models.CharField(max_length=255)

    def toString(self):
        return self.host


"""
0=서버에 인증 유보
1=게이트웨이 인증
"""


class Api(models.Model):
    SCHEME_DELIMETER = "://"
    PLUGIN_CHOICE_LIST = (
        (0, 'Remote auth'),
        (1, 'Basic auth'),
        (2, 'Key auth'),
        (3, 'Server auth')
    )

    class SchemeType(models.TextChoices):
        HTTP = "http"
        HTTPS = "https"
        UNITX = "http+unix"

    name = models.CharField(max_length=128, unique=True)
    request_path = models.CharField(max_length=255)
    wrapped_path = models.CharField(max_length=255)
    scheme = models.CharField(
        max_length=64, choices=SchemeType.choices, default=SchemeType.HTTPS)
    upstream = models.ForeignKey(Upstream, on_delete=models.CASCADE)
    plugin = models.IntegerField(choices=PLUGIN_CHOICE_LIST, default=0)
    consumers = models.ManyToManyField(Consumer, blank=True)

    method_map = {
        'get': requests.get,
        'post': requests.post,
        'put': requests.put,
        'patch': requests.patch,
        'delete': requests.delete
    }
    unix_session: requests_unixsocket.Session

    @property
    def unix_map(self):
        unix_session = requests_unixsocket.Session()
        self.unix_session = unix_session
        return {
            'get': unix_session.get,
            'post': unix_session.post,
            'patch': unix_session.patch,
            "delete": unix_session.delete,
            'put': unix_session.put,
        }

    @property
    def full_path(self):
        return self.scheme + "://" + self.upstream.toString() + self.wrapped_path

    def check_plugin(self, request: MockRequest):
        if self.plugin == 0:
            auth = ThirdPartyAuthentication()
            return True, ''

        elif self.plugin == 1:
            auth = BasicAuthentication()
            user: Optional[AbstractBaseUser] = None
            try:
                authenticated = auth.authenticate(request)
                if authenticated:
                    user, password = authenticated
            except:
                return False, 'Authentication credentials were not provided'

            if user and self.consumers.filter(user=user):
                return True, ''
            else:
                return False, 'permission not allowed'
        elif self.plugin == 2:
            apikey = request.META.get('HTTP_APIKEY')
            consumers = self.consumers.filter(apikey=apikey)
            if consumers.exists():
                return True, ''
            return False, 'apikey need'
        elif self.plugin == 3:
            consumer = self.consumers.all()
            if not consumer.exists():
                return False, 'consumer need'
            request.META['HTTP_AUTHORIZATION'] = "#FIXME"
            return True, ''
        else:
            raise NotImplementedError(
                "plugin %d not implemented" % self.plugin)

    def send_request(self, request: MockRequest) -> requests.Response:
        headers = {}
        # if self.plugin != 1 and request.META.get('HTTP_AUTHORIZATION'):
        headers['Authorization'] = request.META.get(
            'HTTP_AUTHORIZATION')
        # headers['content-type'] = request.content_type
        """
        요청 http://localhost:9000/programs/1/data/
        strip = /service/programs
        full_path = /programs/1/data/
        """
        trailing_path = request.get_full_path().removeprefix(self.request_path)
        url = self.full_path+trailing_path
        method = request.method or 'get'
        method = method.lower()

        if request.FILES is not None and isinstance(request.FILES, dict):
            for k, v in request.FILES.items():
                request.data.pop(k)

        if request.content_type and request.content_type.lower() == 'application/json':
            data = json.dumps(request.data)
            headers['content-type'] = request.content_type
        else:
            data = request.data

        if self.scheme == "http+unix":
            res = self.unix_map[method](url, headers=headers,
                                        data=data, files=request.FILES)
            self.unix_session.close()
            return res
        return self.method_map[method](url, headers=headers, data=data, files=request.FILES)

    def __unicode__(self):
        return self.name

    def __str__(self):
        return self.name

    def get(self, __name: str):
        return self.__getattribute__(__name)
