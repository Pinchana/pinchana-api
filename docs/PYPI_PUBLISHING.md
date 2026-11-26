# Publishing Pinchana packages to PyPI

The PyPI workflow builds the shared core, platform scrapers, and Python bundle
from a release tag. Publishing a stable GitHub Release starts an upload of
all packages on the default branch. The bundle uploads after the core and
platform packages. The gateway is released through GHCR.

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

## Publish selected packages or retry a release

1. Use an existing release tag whose commit is on `main`.
   [Tagging a release](RELEASING.md)
2. In GitHub Actions, open **Publish Python packages to PyPI** and select
   **Run workflow** on `main`. Enter the tag and the exact project names as a
   comma-separated list. Leave **publish** unchecked for a build-only run.
   The workflow saves the checked wheels and source archives in
   `pypi-distributions`.
3. Check **publish** to upload the selected projects. Use `all` for the full
   release. To retry a partial upload, select the unsuccessful projects and
   check **resume** to skip files already on PyPI.

## Build locally

```sh
python scripts/build_pypi.py --projects pinchana-core,pinchana-shorts \
  --out-dir /tmp/pinchana-pypi
uvx twine check --strict /tmp/pinchana-pypi/*/*.whl /tmp/pinchana-pypi/*/*.tar.gz
```

Use a new output directory when rebuilding the same projects.
