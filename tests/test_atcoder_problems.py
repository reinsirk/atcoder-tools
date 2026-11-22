import unittest
from unittest import mock

import requests

from atcodertools.client.atcoder_problems import (
    AtCoderProblemsClient, AtCoderProblemsError, BASE_URL, PROBLEMS_URL,
    REQUEST_TIMEOUT, get_virtual_contest_id,
)


CONTEST_ID = "5337d86a-655c-487a-83f1-6d1b97115757"
CONTEST_TITLE = "WACPAC 練習会 #69"
CONTEST_URL = BASE_URL + "/#/contest/show/" + CONTEST_ID
CONTEST_API_URL = BASE_URL + "/internal-api/contest/get/" + CONTEST_ID
CONTEST_DATA = {"info": {"title": CONTEST_TITLE}, "problems": [
    {"id": "code_festival_2017_qualb_b", "order": 2},
    {"id": "arc058_a", "order": 0},
    {"id": "abc042_a", "order": 1},
]}
PROBLEM_DATA = [
    {"id": "arc058_a", "contest_id": "arc058", "problem_index": "C"},
    {"id": "abc042_a", "contest_id": "abc042", "problem_index": "A"},
    {"id": "code_festival_2017_qualb_b",
        "contest_id": "code-festival-2017-qualb", "problem_index": "B"},
]


def json_response(data):
    response = mock.Mock()
    response.json.return_value = data
    return response


class TestAtCoderProblems(unittest.TestCase):
    def test_recognize_virtual_contest(self):
        for value in [CONTEST_ID, CONTEST_URL, CONTEST_URL + "/", CONTEST_ID.upper()]:
            with self.subTest(value=value):
                self.assertEqual(get_virtual_contest_id(value), CONTEST_ID)
        for value in ["abc123", "code-festival-2017-qualb", "practice"]:
            self.assertIsNone(get_virtual_contest_id(value))

    def test_reject_invalid_urls(self):
        for value in [
            BASE_URL + "/#/contest/show/not-a-uuid",
            BASE_URL + "/#/contest/show/../../abc123",
            BASE_URL + "/#/contest/create",
            CONTEST_URL.replace("kenkoooo.com", "example.com"),
            CONTEST_URL.replace("/atcoder/", "/other/"),
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                get_virtual_contest_id(value)

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_download_title_and_problems_with_one_contest_request(self, get):
        get.side_effect = [json_response(
            CONTEST_DATA), json_response(PROBLEM_DATA)]
        title, problems = AtCoderProblemsClient().download_contest(CONTEST_ID)
        self.assertEqual(title, CONTEST_TITLE)
        self.assertEqual([p.problem_id for p in problems],
                         [p["id"] for p in PROBLEM_DATA])
        self.assertEqual(get.call_args_list, [
            mock.call(CONTEST_API_URL, timeout=REQUEST_TIMEOUT),
            mock.call(PROBLEMS_URL, timeout=REQUEST_TIMEOUT),
        ])

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_missing_or_invalid_title_keeps_problem_list_available(self, get):
        for info in [None, {}, {"title": None}, {"title": 123}]:
            with self.subTest(info=info):
                data = {"info": info, "problems": CONTEST_DATA["problems"]}
                get.side_effect = [json_response(
                    data), json_response(PROBLEM_DATA)]
                title, problems = AtCoderProblemsClient().download_contest(CONTEST_ID)
                self.assertEqual(title, "")
                self.assertEqual(len(problems), 3)

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_download_in_order_with_original_contests_and_alphabets(self, get):
        get.side_effect = [json_response(
            CONTEST_DATA), json_response(PROBLEM_DATA)]
        problems = AtCoderProblemsClient().download_problem_list(CONTEST_ID)
        self.assertEqual([p.get_url() for p in problems], [
            "https://atcoder.jp/contests/arc058/tasks/arc058_a",
            "https://atcoder.jp/contests/abc042/tasks/abc042_a",
            "https://atcoder.jp/contests/code-festival-2017-qualb/tasks/code_festival_2017_qualb_b",
        ])
        self.assertEqual([p.get_alphabet() for p in problems], ["C", "A", "B"])
        self.assertEqual(get.call_args_list, [
            mock.call(CONTEST_API_URL, timeout=REQUEST_TIMEOUT),
            mock.call(PROBLEMS_URL, timeout=REQUEST_TIMEOUT),
        ])

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_network_http_and_json_errors(self, get):
        response = json_response({})
        response.raise_for_status.side_effect = requests.HTTPError(
            "404 Not Found")
        bad_json = json_response({})
        bad_json.json.side_effect = ValueError("invalid JSON")
        for error in [requests.Timeout("timed out"), response, bad_json]:
            with self.subTest(error=error), self.assertRaises(AtCoderProblemsError) as ctx:
                get.side_effect = [error]
                AtCoderProblemsClient().download_problem_list(CONTEST_ID)
            self.assertIn(CONTEST_API_URL, str(ctx.exception))

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_invalid_and_empty_contests_stop_before_dataset_download(self, get):
        for data in [None, [], {}, {"problems": []}, {"problems": None},
                     {"problems": [{"id": "arc058_a"}]},
                     {"problems": [{"id": "arc058_a", "order": "0"}]},
                     {"problems": [{"id": None, "order": 0}]}]:
            with self.subTest(data=data), self.assertRaises(AtCoderProblemsError):
                get.reset_mock()
                get.side_effect = [json_response(data)]
                AtCoderProblemsClient().download_problem_list(CONTEST_ID)
            get.assert_called_once_with(
                CONTEST_API_URL, timeout=REQUEST_TIMEOUT)

    @mock.patch("atcodertools.client.atcoder_problems.requests.get")
    def test_missing_or_invalid_problem_metadata(self, get):
        for data in [None, {}, [], [{"id": "arc058_a"}],
                     [{"id": "arc058_a", "contest_id": "../arc058", "problem_index": "C"}]]:
            with self.subTest(data=data), self.assertRaises(AtCoderProblemsError):
                get.side_effect = [json_response(
                    CONTEST_DATA), json_response(data)]
                AtCoderProblemsClient().download_problem_list(CONTEST_ID)
