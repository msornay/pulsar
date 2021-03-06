'''
sequential
~~~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: sequential


ActorTestMixin
~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: ActorTestMixin
   :members:
   :member-order: bysource


AsyncAssert
~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: AsyncAssert
   :members:
   :member-order: bysource


check server
~~~~~~~~~~~~~~~~~~

.. autofunction:: check_server

'''
import logging
import unittest

import pulsar
from pulsar import (get_actor, send, multi_async, new_event_loop,
                    is_async, format_traceback, ImproperlyConfigured, Future)
from pulsar.apps.data import create_store


__all__ = ['sequential',
           'NOT_TEST_METHODS',
           'ActorTestMixin',
           'AsyncAssert',
           'check_server',
           'test_timeout',
           'dont_run_with_thread']


LOGGER = logging.getLogger('pulsar.test')
NOT_TEST_METHODS = ('setUp', 'tearDown', '_pre_setup', '_post_teardown',
                    'setUpClass', 'tearDownClass')


def skip_test(o):
    return getattr(o, '__unittest_skip__', False)


def skip_reason(o):
    return getattr(o, '__unittest_skip_why__', '')


def expecting_failure(o):
    return getattr(o, '__unittest_expecting_failure__', False)


class TestFailure:

    def __init__(self, exc):
        self.exc = exc
        self.trace = format_traceback(exc)

    def __str__(self):
        return '\n'.join(self.trace)


def sequential(cls):
    '''Decorator for a :class:`~unittest.TestCase` which cause
    its test functions to run sequentially rather than in an
    asynchronous fashion.

    Typical usage::

        import unittest

        from pulsar.apps.test import sequential

        @sequenatial
        class MyTests(unittest.TestCase):
            ...

    You can also run test functions sequentially when using the
    :ref:`sequential <apps-test-sequential>` flag in the command line.
    '''
    cls._sequential_execution = True
    return cls


class test_timeout:

    def __init__(self, timeout):
        self.timeout = timeout

    def __call__(self, f):
        f._test_timeout = self.timeout
        return f


def get_test_timeout(o, timeout):
    val = getattr(o, '_test_timeout', 0)
    return max(val, timeout)


class AsyncAssert(object):
    '''A `descriptor`_ added by the test application to all python
    :class:`~unittest.TestCase` loaded.

    It can be used to invoke the same ``assertXXX`` methods available in
    the :class:`~unittest.TestCase` in an asynchronous fashion.

    The descriptor is available via the ``async`` attribute.
    For example::

        class MyTest(unittest.TestCase):

            def test1(self):
                yield self.async.assertEqual(3, Future().callback(3))
                ...


    .. _descriptor: http://users.rcn.com/python/download/Descriptor.htm
    '''
    def __init__(self, test):
        self.test = test

    def __get__(self, instance, instance_type=None):
        if instance is not None:
            return AsyncAssert(instance)
        else:
            return self

    def __getattr__(self, name):

        def _(*args, **kwargs):
            args = yield from multi_async(args)
            result = getattr(self.test, name)(*args, **kwargs)
            if is_async(result):
                result = yield from result
            return result

        return _

    def assertRaises(self, error, callable, *args, **kwargs):
        try:
            yield from callable(*args, **kwargs)
        except error:
            return
        except Exception:   # pragma    nocover
            raise self.test.failureException('%s not raised by %s'
                                             % (error, callable))
        else:   # pragma    nocover
            raise self.test.failureException('%s not raised by %s'
                                             % (error, callable))


class ActorTestMixin(object):
    '''A mixin for :class:`~unittest.TestCase`.

    Useful for classes testing spawning of actors.
    Make sure this is the first class you derive from, before the
    :class:`~unittest.TestCase`, so that the tearDown method is overwritten.

    .. attribute:: concurrency

        The concurrency model used to spawn actors via the :meth:`spawn`
        method.
    '''
    concurrency = 'thread'

    @property
    def all_spawned(self):
        if not hasattr(self, '_spawned'):
            self._spawned = []
        return self._spawned

    def spawn_actor(self, concurrency=None, **kwargs):
        '''Spawn a new actor and perform some tests
        '''
        concurrency = concurrency or self.concurrency
        ad = pulsar.spawn(concurrency=concurrency, **kwargs)
        self.assertTrue(ad.aid)
        self.assertIsInstance(ad, Future)
        proxy = yield from ad
        self.all_spawned.append(proxy)
        self.assertEqual(proxy.aid, ad.aid)
        self.assertEqual(proxy.proxy, proxy)
        self.assertTrue(proxy.cfg)
        return proxy

    def stop_actors(self, *args):
        all = args or self.all_spawned
        return multi_async([send(a, 'stop') for a in all])

    def tearDown(self):
        return self.stop_actors()


def check_server(name):
    '''Check if server ``name`` is available at the address specified
    ``<name>_server`` config value.

    :rtype: boolean
    '''
    cfg = get_actor().cfg
    addr = cfg.get('%s_server' % name)
    if addr:
        if ('%s://' % name) not in addr:
            addr = '%s://%s' % (name, addr)
        try:
            sync_store = create_store(addr, loop=new_event_loop())
        except ImproperlyConfigured:
            return False
        try:
            sync_store._loop.run_until_complete(sync_store.ping())
            return True
        except Exception:
            return False
    else:
        return False


def dont_run_with_thread(obj):
    '''Decorator for disabling process based test cases when the test suite
    runs in threading, rather than processing, mode.
    '''
    actor = pulsar.get_actor()
    if actor:
        d = unittest.skipUnless(actor.cfg.concurrency == 'process',
                                'Run only when concurrency is process')
        return d(obj)
    else:
        return obj
