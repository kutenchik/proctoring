import pytest

from proctoring.browser_policy import NavigationPolicy


@pytest.mark.parametrize("destination", [
    "https://lms.example.edu/quiz/12",
    "https://lms.example.edu/quiz/12?attempt=3#question-5",
    "https://LMS.EXAMPLE.EDU/course",
    "https://lms.example.edu./course",
    "https://lms.example.edu:8443/course",
])
def test_default_origin_allows_same_host_subpaths(destination):
    policy = NavigationPolicy("https://lms.example.edu/start")
    assert policy.allowed_domains == ("lms.example.edu",)
    assert policy.allows(destination)


@pytest.mark.parametrize("destination", [
    "https://google.com", "https://chatgpt.com",
    "https://lms.example.edu.attacker.test/",
    "https://sub.lms.example.edu/", "https://notlms.example.edu/",
    "https://attacker.test/?next=https://lms.example.edu/",
    "https://lms.example.edu@attacker.test/",
    "https://attacker.test@lms.example.edu/",
    "https://lms.example.edu\\@attacker.test/",
    "https://lms.example.edu%2eattacker.test/",
    "https://lms.example.edu%00.attacker.test/",
    "https://lms.example.edu:bad/", "https://lms.example.edu:70000/",
    "https://lms.example.edu:/",
    "https://lms.example.edu/\nnext", "https://lms.example.edu/\x00next",
    "file:///tmp/exam.html", "data:text/html,hello", "javascript:alert(1)",
    "mailto:student@lms.example.edu", "about:blank", "blob:https://lms.example.edu/test",
    "//lms.example.edu/quiz", "/quiz", "", None,
])
def test_outside_or_ambiguous_navigation_is_rejected(destination):
    assert not NavigationPolicy("https://lms.example.edu/").allows(destination)


def test_additional_login_host_requires_explicit_allowlist_entry():
    policy = NavigationPolicy("https://lms.example.edu/exam", ["lms.example.edu", "login.example.edu"])
    assert policy.allows("https://login.example.edu/sso")
    assert not policy.allows("https://another.example.edu/")


def test_unicode_hosts_share_one_normalized_idna_spelling():
    policy = NavigationPolicy("https://bücher.example/exam", ["BÜCHER.example.", "xn--bcher-kva.example"])
    assert policy.external_url == "https://xn--bcher-kva.example/exam"
    assert policy.allowed_domains == ("xn--bcher-kva.example",)
    assert policy.allows("https://bücher.example/next")


@pytest.mark.parametrize("origin,domains", [
    ("http://127.0.0.1:8123/start", ["127.0.0.1"]),
    ("http://[::1]:8123/start", ["::1"]),
    ("http://localhost:8123/start", ["localhost"]),
])
def test_local_http_origins_are_supported_for_demos(origin, domains):
    policy = NavigationPolicy(origin, domains)
    assert policy.allows(origin)


@pytest.mark.parametrize("domains", [
    ["https://lms.example.edu"], ["*.example.edu"], ["lms.example.edu:443"],
    ["lms.example.edu/path"], [" lms.example.edu"], ["lms.example..edu"],
    ["-lms.example.edu"], ["lms.example.edu", 42], "lms.example.edu", None,
    ["other.example.edu"],
])
def test_bad_or_origin_excluding_allowlist_fails_configuration(domains):
    with pytest.raises(ValueError):
        NavigationPolicy("https://lms.example.edu/", domains)


@pytest.mark.parametrize("url", [
    "", "lms.example.edu", "ftp://lms.example.edu", "https:///exam",
    "https://user:password@lms.example.edu", "https://lms.example.edu:65536",
    "https://lms.example.edu/with space", "https://lms.example.edu\\evil", 42, None,
    "https://[::1]evil.test/", "http://[fe80::1%eth0]/",
])
def test_bad_initial_url_fails_configuration(url):
    with pytest.raises(ValueError):
        NavigationPolicy(url)
