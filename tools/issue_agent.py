import os

import requests


REPO = "JohanSjoblom/picochess"


def main():
    token = os.environ["GITHUB_TOKEN"]

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    url = f"https://api.github.com/repos/{REPO}/issues"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    issues = response.json()

    for issue in issues[:5]:
        print(issue["title"])


if __name__ == "__main__":
    main()
