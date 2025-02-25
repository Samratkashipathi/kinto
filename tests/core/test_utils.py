import os
import unittest
from unittest import mock

import colander
from pyramid import httpexceptions
from pyramid import request as pyramid_request
from pyramid import testing

from kinto.core import DEFAULT_SETTINGS, includeme
from kinto.core.testing import DummyRequest
from kinto.core.utils import (
    build_request,
    current_service,
    dict_merge,
    dict_subset,
    find_nested_value,
    follow_subrequest,
    hmac_digest,
    instance_uri_registry,
    native_value,
    prefixed_principals,
    random_bytes_hex,
    read_env,
    recursive_update_dict,
    strip_whitespace,
)


def build_real_request(wsgi_environ):
    """Build a Pyramid request, as if it was instantiated by Pyramid.
    """
    config = testing.setUp(settings=DEFAULT_SETTINGS)
    includeme(config)
    request = pyramid_request.Request(wsgi_environ)
    request.registry = config.registry
    return request


class NativeValueTest(unittest.TestCase):
    def test_simple_string(self):
        self.assertEqual(native_value("value"), "value")

    def test_defined_string(self):
        self.assertEqual(native_value('"value"'), "value")

    def test_null_value(self):
        self.assertEqual(native_value("null"), None)

    def test_defined_null_as_text_value(self):
        self.assertEqual(native_value('"null"'), "null")

    def test_integer(self):
        self.assertEqual(native_value("7"), 7)

    def test_defined_integer_as_text_value(self):
        self.assertEqual(native_value('"7"'), "7")

    def test_defined_simple_quote_string_as_text_value(self):
        self.assertEqual(native_value("'7'"), "'7'")

    def test_zero_and_one_coerce_to_integers(self):
        self.assertEqual(native_value("1"), 1)
        self.assertEqual(native_value("0"), 0)

    def test_float(self):
        self.assertEqual(native_value("3.14"), 3.14)

    def test_true_values(self):
        true_strings = ["true"]
        true_values = [native_value(s) for s in true_strings]
        self.assertTrue(all(true_values))

    def test_false_values(self):
        false_strings = ["false"]
        false_values = [native_value(s) for s in false_strings]
        self.assertFalse(any(false_values))

    def test_non_string_values(self):
        self.assertEqual(native_value(7), 7)
        self.assertEqual(native_value(True), True)

    def test_bad_string_values(self):
        self.assertEqual(native_value("\u0000"), "\x00")


class StripWhitespaceTest(unittest.TestCase):
    def test_removes_all_kinds_of_spaces(self):
        value = " \t teaser \n \r"
        self.assertEqual(strip_whitespace(value), "teaser")

    def test_does_remove_middle_spaces(self):
        self.assertEqual(strip_whitespace("a b c"), "a b c")

    def test_idempotent_for_null_values(self):
        self.assertEqual(strip_whitespace(colander.null), colander.null)


class CryptographicRandomBytesTest(unittest.TestCase):
    def test_return_hex_string(self):
        value = random_bytes_hex(16)
        try:
            int(value, 16)
        except ValueError:
            self.fail("{} is not an hexadecimal value.".format(value))

    def test_return_right_length_string(self):
        for x in range(2, 4):
            value = random_bytes_hex(x)
            self.assertEqual(len(value), x * 2)

    def test_return_text_string(self):
        value = random_bytes_hex(16)
        self.assertIsInstance(value, str)


class HmacDigestTest(unittest.TestCase):
    def test_supports_secret_as_text(self):
        value = hmac_digest("blah", "input data")
        self.assertTrue(value.startswith("d4f5c51db246c7faeb42240545b47274b6"))

    def test_supports_secret_as_bytes(self):
        value = hmac_digest(b"blah", "input data")
        self.assertTrue(value.startswith("d4f5c51db246c7faeb42240545b47274b6"))


class ReadEnvironmentTest(unittest.TestCase):
    def test_return_passed_value_if_not_defined_in_env(self):
        self.assertEqual(read_env("missing", 12), 12)

    def test_return_env_value_if_defined_in_env(self):
        os.environ.setdefault("KINTO_CONF", "abc")
        self.assertEqual(read_env("KINTO_CONF", 12), "abc")

    def test_return_env_name_as_uppercase(self):
        os.environ.setdefault("KINTO_NAME", "abc")
        self.assertEqual(read_env("kinto.name", 12), "abc")

    def test_return_env_value_is_coerced_to_python(self):
        os.environ.setdefault("KINTO_CONF_NAME", "3.14")
        self.assertEqual(read_env("kinto-conf.name", 12), 3.14)

    def test_default_value_is_not_coerced_to_python(self):
        self.assertEqual(read_env("kinto-conf.name", "12"), "12")


class CurrentServiceTest(unittest.TestCase):
    def test_current_service_returns_the_service_for_existing_patterns(self):
        request = DummyRequest()
        request.matched_route.pattern = "/buckets"
        request.registry.cornice_services = {"/buckets": mock.sentinel.service}

        self.assertEqual(current_service(request), mock.sentinel.service)

    def test_current_service_returns_none_for_unexisting_patterns(self):
        request = DummyRequest()
        request.matched_route.pattern = "/unexisting"
        request.registry.cornice_services = {}

        self.assertEqual(current_service(request), None)


class PrefixedPrincipalsTest(unittest.TestCase):
    def test_removes_unprefixed_from_principals(self):
        request = DummyRequest()
        request.effective_principals = ["foo", "system.Authenticated"]
        request.prefixed_userid = "basic:foo"
        self.assertEqual(prefixed_principals(request), ["basic:foo", "system.Authenticated"])

    def test_works_if_userid_is_not_in_principals(self):
        request = DummyRequest()
        request.effective_principals = ["basic:foo", "system.Authenticated"]
        request.prefixed_userid = "basic:foo"
        self.assertEqual(prefixed_principals(request), ["basic:foo", "system.Authenticated"])


class BuildRequestTest(unittest.TestCase):
    def test_built_request_has_kinto_core_custom_methods(self):
        original = build_real_request({"PATH_INFO": "/foo"})
        request = build_request(original, {"path": "bar"})
        self.assertTrue(hasattr(request, "current_service"))


class FollowSubrequestTest(unittest.TestCase):
    def test_parent_and_bound_data_are_preserved(self):
        request = DummyRequest()
        request.invoke_subrequest.side_effect = (httpexceptions.HTTPTemporaryRedirect, None)
        subrequest = DummyRequest()
        subrequest.parent = mock.sentinel.parent
        subrequest.bound_data = mock.sentinel.bound_data
        _, redirected = follow_subrequest(request, subrequest)
        self.assertEqual(subrequest.parent, redirected.parent)
        self.assertEqual(subrequest.bound_data, redirected.bound_data)


class DictSubsetTest(unittest.TestCase):
    def test_extract_by_keys(self):
        obtained = dict_subset(dict(a=1, b=2), ["b"])
        expected = dict(b=2)
        self.assertEqual(obtained, expected)

    def test_is_noop_if_no_keys(self):
        obtained = dict_subset(dict(a=1, b=2), [])
        expected = dict()
        self.assertEqual(obtained, expected)

    def test_ignores_unknown_keys(self):
        obtained = dict_subset(dict(a=1, b=2), ["a", "a.b", "d.b", "c"])
        expected = dict(a=1)
        self.assertEqual(obtained, expected)

    def test_ignores_duplicated_keys(self):
        obtained = dict_subset(dict(a=1, b=2), ["a", "a"])
        expected = dict(a=1)
        self.assertEqual(obtained, expected)

    def test_can_filter_subobjects(self):
        obtained = dict_subset(dict(a=1, b=dict(c=2, d=3)), ["a", "b.c"])
        expected = dict(a=1, b=dict(c=2))
        self.assertEqual(obtained, expected)

    def test_can_filter_subobjects_keys(self):
        input = dict(a=1, b=dict(c=2, d=3, e=4))
        obtained = dict_subset(input, ["a", "b.d", "b.e"])
        expected = dict(a=1, b=dict(d=3, e=4))
        self.assertEqual(obtained, expected)

    def test_can_filter_subobjects_recursively(self):
        input = dict(b=dict(c=2, d=dict(e=4, f=5, g=6)))
        obtained = dict_subset(input, ["b.d.e", "b.d.f"])
        expected = dict(b=dict(d=dict(e=4, f=5)))
        self.assertEqual(obtained, expected)

    def test_ignores_if_subobject_is_not_dict(self):
        input = dict(a=1, b=dict(c=2, d=3))
        obtained = dict_subset(input, ["a", "b.c.d", "b.d"])
        expected = dict(a=1, b=dict(c=2, d=3))
        self.assertEqual(obtained, expected)


class DictMergeTest(unittest.TestCase):
    def test_merge(self):
        obtained = dict_merge(dict(a=1, b=dict(c=2)), dict(b=dict(d=4)))
        expected = dict(a=1, b=dict(c=2, d=4))
        self.assertEqual(obtained, expected)


class FindNestedValueTest(unittest.TestCase):
    def test_find_flat_value(self):
        obj = {"a": 42}
        obtained = find_nested_value(obj, "a")
        self.assertEqual(obtained, 42)

    def test_find_nested_value(self):
        obj = {"a": {"b": 42}}
        obtained = find_nested_value(obj, "a.b")
        self.assertEqual(obtained, 42)

    def test_find_deeply_nested_value(self):
        obj = {"a": {"b": {"c": 42}}}
        obtained = find_nested_value(obj, "a.b.c")
        self.assertEqual(obtained, 42)

    def test_find_dotted_path_value(self):
        obj = {"a.b": 42}
        obtained = find_nested_value(obj, "a.b")
        self.assertEqual(obtained, 42)

    def test_find_nested_dotted_path_value(self):
        obj = {"a": {"b.c": 42}}
        obtained = find_nested_value(obj, "a.b.c")
        self.assertEqual(obtained, 42)

        obj = {"a.b": {"c.d": 42}}
        obtained = find_nested_value(obj, "a.b.c.d")
        self.assertEqual(obtained, 42)

        obj = {"a": {"b": {"a": {"b": 42}}}}
        obtained = find_nested_value(obj, "a.b.a.b")
        self.assertEqual(obtained, 42)

    def test_find_disambiguated_dotted_path_values(self):
        # XXX: To be honest, this is a really scary use case. Probably a
        # limitation of the dotted path notation we may want to document.
        # At least this test acts as documentation for now.
        obj = {"a": {"b": 0}, "a.b": 42}
        obtained = find_nested_value(obj, "a.b")
        self.assertEqual(obtained, 42)

    def test_unmatched_path_returns_none(self):
        obj = {"a": 42}
        self.assertIsNone(find_nested_value(obj, "x"))
        self.assertIsNone(find_nested_value(obj, "a.b"))
        self.assertIsNone(find_nested_value(obj, "x.a"))

    def test_fallback_default_value(self):
        obj = {"a": {"c": 42}}
        self.assertEqual(find_nested_value(obj, "x", 1337), 1337)
        self.assertEqual(find_nested_value(obj, "a.b", 1337), 1337)
        self.assertEqual(find_nested_value(obj, "x.a", 1337), 1337)
        self.assertEqual(find_nested_value(obj, "a.c.d", 1337), 1337)


class RecursiveUpdateDictTest(unittest.TestCase):
    def test_merge(self):
        a = {}
        recursive_update_dict(a, {"b": {"c": 1}, "d": 2})
        self.assertEqual(a["b"]["c"], 1)
        self.assertEqual(a["d"], 2)

    def test_merge_non_dict(self):
        a = {}
        recursive_update_dict(a, 1)
        self.assertEqual(a, {})


class InstanceURIRegistryTest(unittest.TestCase):
    @mock.patch("kinto.core.utils.instance_uri")
    def test_instance_uri_registry_calls_instance_uri(self, instance_uri):
        registry = mock.Mock()
        instance_uri_registry(registry, "object", a=1)
        self.assertEqual(len(instance_uri.call_args_list), 1)
        (args, kwargs) = instance_uri.call_args_list[0]
        self.assertEqual(len(args), 2)

        self.assertEqual(args[0].registry, registry)
        self.assertEqual(args[1], "object")

        self.assertEqual(kwargs, {"a": 1})
