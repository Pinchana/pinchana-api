# Publishing Pinchana packages to PyPI

The PyPI workflow builds the shared core, platform scrapers, and Python bundle
from a release tag. Run it manually for each batch. The gateway is released
through GHCR.

## Register the Trusted Publishers

Use these GitHub settings for each PyPI registration.

| PyPI field | Value |
| --- | --- |
| Owner | `Pinchana` |
| Repository name | `pinchana-api` |
| Workflow name | `publish-pypi.yml` |

Enter the project and environment name from this table.

| PyPI Project Name | Environment name |
| --- | --- |
| `pinchana-core` | `pypi` |
| `pinchana-apple-music` | `pypi-pinchana-apple-music` |
| `pinchana-bluesky` | `pypi-pinchana-bluesky` |
| `pinchana-coub` | `pypi-pinchana-coub` |
| `pinchana-deezer` | `pypi-pinchana-deezer` |
| `pinchana-inst` | `pypi-pinchana-inst` |
| `pinchana-shorts` | `pypi-pinchana-shorts` |
| `pinchana-soundcloud` | `pypi-pinchana-soundcloud` |
| `pinchana-spotify` | `pypi-pinchana-spotify` |
| `pinchana-threads` | `pypi-pinchana-threads` |
| `pinchana-tiktok` | `pypi-pinchana-tiktok` |
| `pinchana-twitter` | `pypi-pinchana-twitter` |
| `pinchana-ytgroups` | `pypi-pinchana-ytgroups` |
| `pinchana-ytmusic` | `pypi-pinchana-ytmusic` |
| `pinchana-scraper` | `pypi-pinchana-scraper` |

For new projects, add pending publishers from your account's Publishing page.
Register up to three at a time. A successful first publish activates the
publisher and frees its pending slot. For an existing project you manage, add
the publisher from that project's Publishing page. [Pending publisher setup](https://pypi.org/manage/account/publishing/) · [PyPI Trusted Publishing guide](https://docs.pypi.org/trusted-publishers/)

On GitHub, the matching repository environments must allow deployments from
`main`, since the workflow runs from `main` and builds the source at the
selected tag. [GitHub environments](https://github.com/Pinchana/pinchana-api/settings/environments)

## Build and publish the first release

1. Land the packages and publishing workflow on `main`, then create a fresh
   release tag using the repository release process. Use the same tag for
   every batch of the first PyPI release. [Tagging a release](RELEASING.md)
2. In GitHub Actions, open **Publish Python packages to PyPI** and select
   **Run workflow** on `main`. Enter the tag and the exact project names as a
   comma-separated list. Leave **publish** unchecked for a build-only run.
   The workflow saves the checked wheels and source archives in
   `pypi-distributions`.
3. Run the workflow again with **publish** checked for `pinchana-core`.
   Confirm its release on PyPI before publishing the platform scrapers.
4. Publish the other registered projects, then register the next batch in
   the slots freed by the uploads. Publish `pinchana-scraper` after all 13
   platform scrapers and the core are available at the release version.

For later releases, select `all` once all publishers are active. Start a new
run with just the unsuccessful projects if a batch partly succeeds. If a
project already has one distribution file for that tag, select **resume**
to upload the missing file for the same release.

## Build locally

```sh
python scripts/build_pypi.py --projects pinchana-core,pinchana-shorts \
  --out-dir /tmp/pinchana-pypi
uvx twine check --strict /tmp/pinchana-pypi/*/*.whl /tmp/pinchana-pypi/*/*.tar.gz
```

Use a new output directory when rebuilding the same projects.
