# Git history consolidation — 17 September 2026

The owner authorized consolidation of the study and replacement of its GitHub history.
`git filter-branch` removed `site/assets` from historical commits, retaining the complete
current report tree at original commit `b2c4c7cd052b36cf2c4b7c8552af3acc2aeb51ee`.
That unchanged tree is now commit `da083363bb34abe09b251dded13dd5a48c1d3e7a`, selected
by tag `report-2026-09-17-adox-alignment`. The consolidation launcher is a later commit.

The full [old-to-new commit map](history-commit-map.tsv) preserves the identity mapping.
Branches and tags are rewritten consistently. Older checkouts retain their source and
records, but their generated report assets were removed; an older tag is therefore
not a complete historical visual report. Use the preserved original history when an
exact old snapshot is needed. The current report tree and current assets were kept
byte-for-byte, and its regenerated site was compared with all 2,993 frozen files.

The private, Git-ignored `archive/study-20260917/git/original-history.bundle` preserves
original reachable refs and history. Its adjacent `lfs/objects` preserves the available
LFS payloads separately. See the archive README for restoration commands. The bundle
was restored and checked with `git fsck` before the rewrite. It is not published because
it deliberately contains the removed historical bulk.

After the rewrite, ordinary Git objects occupied about 959 MiB, down from about
4.3 GiB. LFS objects are accounted for separately. Rewriting refs does not itself delete
server-side LFS objects or guarantee immediate garbage collection of GitHub-retained
PR/internal objects. The advertised branches and tags define the new normal clone.

Existing clones should be replaced with a fresh clone, or deliberately reconciled
using the mapping after preserving local changes. Do not merge the old history back
into the new main branch: doing so restores the removed history. Machine-local rewrite,
validation and remote-ref receipts are retained in the consolidated project archive.
