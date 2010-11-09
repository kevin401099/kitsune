import imghdr
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.http import (HttpResponse, HttpResponseNotFound,
                         HttpResponseBadRequest, Http404,
                         HttpResponseRedirect)
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from commonware.decorators import xframe_sameorigin
import jingo
from tower import ugettext as _

from gallery import ITEMS_PER_PAGE
from sumo.utils import paginate
from sumo.urlresolvers import reverse
from upload.utils import FileTooLargeError
from .models import Image, Video
from .utils import upload_image, upload_video

MSG_LIMIT_ONE = {'image': _('You may only upload one image at a time.'),
                 'video': _('You may only upload one video at a time.')}
MSG_FAIL_UPLOAD = {'image': _('Could not upload your image.'),
                   'video': _('Could not upload your video.')}


def gallery(request, media_type='image'):
    """The media gallery.

    Filter can be set to 'images' or 'videos'.

    """
    if media_type == 'image':
        media_qs = Image.objects.filter(locale=request.locale)
    elif media_type == 'video':
        media_qs = Video.objects.filter(locale=request.locale)
    else:
        raise Http404

    media = paginate(request, media_qs, per_page=ITEMS_PER_PAGE)

    return jingo.render(request, 'gallery/gallery.html',
                        {'media': media,
                         'media_type': media_type})


def gallery_async(request):
    """AJAX endpoint to media gallery.

    Returns an HTML list representation of the media.

    """
    # Maybe refactor this into existing views and check request.is_ajax?
    media_type = request.GET.get('type', 'image')
    term = request.GET.get('q')
    if media_type == 'image':
        media_qs = Image.objects
    elif media_type == 'video':
        media_qs = Video.objects
    else:
        raise Http404

    if request.locale == settings.WIKI_DEFAULT_LANGUAGE:
        media_qs = media_qs.filter(locale=request.locale)
    else:
        locales = [request.locale, settings.WIKI_DEFAULT_LANGUAGE]
        media_qs = media_qs.filter(locale__in=locales)

    if term:
        media_qs = media_qs.filter(Q(title__icontains=term) |
                                   Q(description__icontains=term))

    media = paginate(request, media_qs, per_page=ITEMS_PER_PAGE)

    return jingo.render(request, 'gallery/includes/media_list.html',
                        {'media_list': media})


def search(request, media_type):
    """Search the media gallery."""

    term = request.GET.get('q')
    if not term:
        url = reverse('gallery.gallery_media', args=[media_type])
        return HttpResponseRedirect(url)

    filter = Q(title__icontains=term) | Q(description__icontains=term)

    if media_type == 'image':
        media_qs = Image.objects.filter(filter, locale=request.locale)
    elif media_type == 'video':
        media_qs = Video.objects.filter(filter, locale=request.locale)
    else:
        raise Http404

    media = paginate(request, media_qs, per_page=ITEMS_PER_PAGE)

    return jingo.render(request, 'gallery/search.html',
                        {'media': media,
                         'media_type': media_type,
                         'q': term})


def media(request, media_id, media_type='image'):
    """The media page."""
    media_format = None
    if media_type == 'image':
        media = get_object_or_404(Image, pk=media_id)
        media_format = imghdr.what(media.file.path)
    elif media_type == 'video':
        media = get_object_or_404(Video, pk=media_id)
    else:
        raise Http404

    return jingo.render(request, 'gallery/media.html',
                        {'media': media,
                         'media_format': media_format,
                         'media_type': media_type})


@login_required
@require_POST
@xframe_sameorigin
def up_media_async(request, media_type='image'):
    """Upload images or videos from request.FILES."""

    try:
        if media_type == 'image':
            file_info = upload_image(request)
        else:
            file_info = upload_video(request)
    except FileTooLargeError as e:
        return HttpResponseBadRequest(
            json.dumps({'status': 'error', 'message': e.args[0]}))

    if isinstance(file_info, dict) and 'thumbnail_url' in file_info:
        return HttpResponse(
            json.dumps({'status': 'success', 'file': file_info}))

    message = MSG_FAIL_UPLOAD[media_type]
    return HttpResponseBadRequest(
        json.dumps({'status': 'error', 'message': message,
                    'errors': file_info}))


@login_required
@require_POST
@xframe_sameorigin
def del_media_async(request, media_id, media_type='image'):
    """Delete a media object given its id."""
    model_class = ContentType.objects.get(model=media_type).model_class()
    try:
        media = model_class.objects.get(pk=media_id)
    except Image.DoesNotExist:
        message = _('The requested media (%s) could not be found.') % media_id
        return HttpResponseNotFound(
            json.dumps({'status': 'error', 'message': message}))

    # Extra care: clean up all the files individually
    media.delete()

    return HttpResponse(json.dumps({'status': 'success'}))