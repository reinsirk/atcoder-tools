import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

import requests

from atcodertools.client.models.contest import Contest
from atcodertools.client.models.problem import Problem


BASE_URL = "https://kenkoooo.com/atcoder"
PROBLEMS_URL = BASE_URL + "/resources/problems.json"
REQUEST_TIMEOUT = 30


class AtCoderProblemsError(Exception):
    pass


def get_virtual_contest_id(value: str) -> Optional[str]:
    """Recognize a virtual contest URL or UUID; leave ordinary contest IDs alone."""
    if "://" in value:
        url = urlparse(value)
        match = re.fullmatch(r"/contest/show/([^/]+)/?", url.fragment)
        if (url.scheme not in ("http", "https") or url.netloc != "kenkoooo.com"
                or url.path.rstrip("/") != "/atcoder" or match is None):
            raise ValueError("Expected an AtCoder Problems virtual contest URL: "
                             + BASE_URL + "/#/contest/show/{contest_id}")
        value = match.group(1)
        try:
            return str(UUID(value))
        except ValueError as e:
            raise ValueError(
                "Invalid virtual contest ID: {}".format(value)) from e

    try:
        return str(UUID(value))
    except ValueError:
        return None


class AtCoderProblemsClient:
    """Read public virtual contests without using the AtCoder login session."""

    def _get_json(self, url):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as e:
            raise AtCoderProblemsError(
                "Failed to fetch AtCoder Problems data from {}: {}".format(url, e)) from e

    def download_problem_list(self, contest_id: str) -> List[Problem]:
        return self.download_contest(contest_id)[1]

    def download_contest(self, contest_id: str) -> Tuple[str, List[Problem]]:
        """Fetch the title and ordered problems together, using one contest request."""
        contest_id = str(UUID(contest_id))
        data = self._get_json(
            BASE_URL + "/internal-api/contest/get/" + contest_id)
        if not isinstance(data, dict) or not isinstance(data.get("problems"), list):
            raise AtCoderProblemsError(
                "Invalid virtual contest response: expected a problem list.")
        info = data.get("info")
        title = info.get("title", "") if isinstance(info, dict) else ""
        if not isinstance(title, str):
            title = ""
        entries = data["problems"]
        if not entries:
            raise AtCoderProblemsError(
                "The virtual contest has no problems or is not publicly accessible.")
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                    or not entry["id"] or type(entry.get("order")) is not int):
                raise AtCoderProblemsError(
                    "Invalid virtual contest problem: expected an ID and an integer order.")

        # A task ID does not always identify its original contest or alphabet.
        # Use the official dataset, including shared ABC/ARC tasks and old contests.
        problems = self._get_json(PROBLEMS_URL)
        if not isinstance(problems, list):
            raise AtCoderProblemsError(
                "Invalid AtCoder Problems dataset: expected a problem list.")
        problem_map = {p["id"]: p for p in problems
                       if isinstance(p, dict) and isinstance(p.get("id"), str)}
        result = []
        for entry in sorted(entries, key=lambda p: p["order"]):
            problem_id = entry["id"]
            problem = problem_map.get(problem_id)
            if problem is None:
                raise AtCoderProblemsError(
                    "Problem {} is missing from the AtCoder Problems dataset.".format(problem_id))
            contest_id = problem.get("contest_id")
            alphabet = problem.get("problem_index")
            if (not isinstance(contest_id, str) or not re.fullmatch(r"[A-Za-z0-9_+~'-]+", contest_id)
                    or not re.fullmatch(r"[A-Za-z0-9_]+", problem_id)
                    or not isinstance(alphabet, str) or not alphabet):
                raise AtCoderProblemsError(
                    "Invalid AtCoder Problems data for problem {}.".format(problem_id))
            result.append(Problem(Contest(contest_id), alphabet, problem_id))
        return title, result
