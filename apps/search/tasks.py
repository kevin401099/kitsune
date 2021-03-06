import datetime
import logging
import sys
from time import time

from django.conf import settings
from django.core.cache import cache

from celery.decorators import task

from search.es_utils import es_reindex_with_progress


# This is present in memcached when reindexing is in progress and
# holds a float value between 0 and 100. When reindexing is complete
# (even if it crashes), the token is removed.
ES_REINDEX_PROGRESS = 'sumo:search:es_reindex_progress'

log = logging.getLogger('k.task')


@task
def reindex_with_progress(write_index):
    """Rebuild elasticsearch index while updating progress bar for admins.
    """
    # Need to import Record here to prevent circular import
    from search.models import Record

    rec = Record(
        starttime=datetime.datetime.now(),
        text=u'Reindexing into %s' % write_index)
    rec.save()
    try:
        # Init progress bar stuff:
        cache.set(ES_REINDEX_PROGRESS, 0.001)  # An iota so it tests
                                               # true in the template

        # Reindex:
        start = time()
        for ratio in es_reindex_with_progress():
            now = time()
            if now > start + settings.ES_REINDEX_PROGRESS_BAR_INTERVAL:
                # Update memcached only every so often.
                start = now
                # Format the string to avoid exponential notation,
                # which seems to be understood by JS but makes me
                # nervous:
                cache.set(ES_REINDEX_PROGRESS, '%.5f' % ratio)

        rec.endtime = datetime.datetime.now()
        rec.save()
    except Exception:

        rec.text = (u'%s: Errored out %s %s' % (
                rec.text, sys.exc_type, sys.exc_value))
        rec.endtime = datetime.datetime.now()
        rec.save()
        raise
    finally:
        cache.delete(ES_REINDEX_PROGRESS)


# Note: If you reduce the length of RETRY_TIMES, it affects all tasks
# currently in the celery queue---they'll throw an IndexError.
RETRY_TIMES = (
    60,           # 1 minute
    5 * 60,       # 5 minutes
    10 * 60,      # 10 minutes
    30 * 60,      # 30 minutes
    60 * 60,      # 60 minutes
    2 * 60 * 60,  # 2 hours
    6 * 60 * 60   # 6 hours
    )
MAX_RETRIES = len(RETRY_TIMES)


@task
def index_task(cls, ids, **kw):
    """Index documents specified by cls and ids"""
    try:
        for id in cls.uncached.filter(id__in=ids).values_list('id', flat=True):
            cls.index(cls.extract_document(id), refresh=True)
    except Exception, exc:
        retries = index_task.request.retries
        index_task.retry(exc=exc, max_retries=MAX_RETRIES - 1,
                         countdown=RETRY_TIMES[retries])


@task
def unindex_task(cls, ids, **kw):
    """Unindex documents specified by cls and ids"""
    try:
        for id in ids:
            cls.unindex(id)
    except Exception, exc:
        retries = unindex_task.request.retries
        unindex_task.retry(exc=exc, max_retries=MAX_RETRIES - 1,
                           countdown=RETRY_TIMES[retries])
