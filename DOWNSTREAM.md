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

Instance isolation is a generic, opt-in MiniStack extension:

- With `MINISTACK_INSTANCE_ID` unset, names, labels, cleanup filters, health
  response shape, and tests retain upstream behavior.
- With `MINISTACK_INSTANCE_ID` set, Docker child containers and persistent
  volumes receive an additive instance scope. Cleanup verifies those ownership
  labels before removing anything.
- Scoped health responses add `instance_isolation` with the contract version,
  full instance ID, short Docker scope, and Docker network.
- The Anbo plugin supplies and verifies this contract, but the variable and
  behavior are not Anbo-branded and can be proposed upstream unchanged.

The AWS endpoints and SDK surface do not change between modes. Existing
MiniStack users do not need to adopt the extension.

## Downstream patch inventory

Keep the behavioral patch deliberately small:

1. `ministack/core/docker_scope.py` owns the entire naming, labeling, and
   destructive-operation guard contract.
2. `ministack/app.py` conditionally exposes the health contract and selects
   scoped lifecycle cleanup.
3. The eight Docker-backed service modules (`rds`, `ecs`, `elasticache`, `eks`,
   `lambda_svc`, `opensearch`, `mwaa`, and `glue`) call the centralized helpers
   at their existing launch and cleanup points.
4. New downstream behavioral regression tests live in `tests_anbo/`; do not
   add them to or rewrite imported upstream test modules.
5. Downstream policy, release, and sync automation remains in additive files
   where possible. In particular, `.github/workflows/anbo-downstream-ci.yml`
   keeps downstream jobs out of upstream's `ci.yml`.

`.github/downstream-docker-ownership.json` records the reviewed Docker launch
count for each service. `scripts/check_docker_ownership.py` discovers
`containers.run` and `containers.create` calls with Python's AST. CI fails when
upstream adds a new Docker-backed service, adds a launch path, removes a
reviewed path, or stops using the ownership helpers. Updating the manifest is a
review acknowledgement, not a way to skip adding isolation.

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
never resolves merge conflicts automatically.

For a clean merge, upstream and downstream tests run independently. Imported
upstream test modules run with `MINISTACK_INSTANCE_ID` unset. The additive
`Anbo downstream CI` workflow runs only `tests_anbo/`, and the static ownership
policy reviews all Docker launch points.

For a conflicting merge, the workflow:

1. Aborts the unreviewed merge rather than choosing either side.
2. Pushes the `sync/ministack-*` review branch with a conflict report under
   `.github/upstream-conflicts/`.
3. Opens or updates an issue containing the branch, exact upstream commit,
   conflicting paths, and resume commands.
4. Surfaces an already-existing sync branch on every later run, including an
   issue when no pull request is open.

Resolve the conflicts on that same branch, remove the temporary conflict report,
run every CI gate, and open or update the pull request. Do not recreate the
downstream changes by copying whole upstream files; reapply only the helper
calls at changed launch or lifecycle points.

## Upstream removal path

The preferred end state is for upstream MiniStack to accept the generic
`MINISTACK_INSTANCE_ID` contract. Once an upstream release contains an
equivalent contract and the Anbo plugin accepts its health version:

1. Replace the downstream helper with the upstream implementation.
2. Remove service-level patches already supplied upstream.
3. Delete redundant `tests_anbo/` cases only after equivalent upstream
   regressions cover same-daemon isolation.
4. Retain the distribution, provenance, image, and packed Anbo CLI acceptance
   gates.

This makes manual work necessary only for genuine lifecycle changes or merge
conflicts, not for every upstream release.
