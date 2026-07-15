# Anbo MiniStack distribution

Anbo MiniStack is the Anbo-maintained container distribution of the upstream
[MiniStack](https://github.com/ministackorg/ministack) AWS emulator. It is a
runtime dependency of the Anbo MiniStack plugin, not a second Anbo CLI.

## Compatibility boundary

Downstream changes should stay in packaging, release automation, security, and
Anbo compatibility checks. Do not rename the `ministack` Python package,
`ministack` executable, `MINISTACK_*` variables, `/_ministack/*` endpoints, or
internal labels. Keeping these identifiers intact makes upstream merges small
and preserves compatibility with the upstream ecosystem.

## Images and versions

Images are published only to `ghcr.io/getanbo/anbo-ministack`:

- `X.Y.Z-anbo.N` is the immutable regular image.
- `X.Y.Z-anbo.N-full` is the immutable full image.
- `rc-X.Y.Z-anbo.N` and its `-full` variant are release candidates.
- `candidate-<git-sha>` and its `-full` variant are integration candidates.

`X.Y.Z` identifies the upstream MiniStack release and `N` is the downstream
Anbo revision. Published release tags are never overwritten. The release
workflow promotes the already tested `rc-*` image indexes by digest; it does
not rebuild them.

## Release procedure

1. Run the `Anbo image candidate` workflow from `main` with a release version
   such as `1.4.2-anbo.1`.
2. Let the candidate build, upstream tests, vulnerability scan, SBOM,
   provenance, and signature checks complete.
3. Tag the same commit `v1.4.2-anbo.1` and push the tag.
4. The release workflow verifies and promotes the candidate digests, then
   publishes a GitHub release with a machine-readable release manifest and
   CycloneDX SBOMs.

The release manifest records upstream provenance, exact multi-platform image
digests, the source commit, and a capability hash. Consumers must pin the image
index digest from that manifest rather than a mutable tag.

## Upstream updates

`.github/upstream.json` records the exact upstream release and commit. The
scheduled `Upstream MiniStack sync` workflow checks for a newer release and
opens a `sync/ministack-*` pull request. It never updates `main` directly and
never resolves merge conflicts automatically. A conflicting sync creates an
issue with the conflicting paths for manual review.
