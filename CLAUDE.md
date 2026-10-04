# Project notes for Claude

## Fork and upstream-sync policy

This repository is a personal fork (`origin` = henryz78/DouYinSparkFlow) of the
official project (`upstream` = 2061360308/DouYinSparkFlow). It carries many
custom changes beyond upstream, and it is meant to keep tracking upstream
releases closely.

Whenever the user says upstream has released a new version, Claude does the merge:

1. `git fetch --all --tags`, then compare the release against our last merge base.
   Read the release notes and the actual diff (`git diff <base> <tag>`), not just the commit titles.
2. **Before merging, check whether upstream's changes overlap with anything we
   previously modified or fixed** (same files, same behaviour, or a feature we
   built ourselves that upstream now also provides). A trial merge
   (`git merge --no-commit --no-ff <tag>`) is a quick way to find the conflicts.
3. For every overlap, evaluate which side is better and decide: keep ours,
   take upstream's, or combine both. Prefer upstream's version when it is
   good enough, because fewer custom lines means fewer conflicts on the next
   release. Keep ours only when it does something upstream does not.
4. Tell the user about each conflict point together with your recommendation
   (what overlaps, which side you suggest keeping and why, any behaviour change
   they will notice, and any risk to the running production container) before
   or alongside doing the merge.
5. Run the full test suite after the merge. Do not push or deploy to the VPS
   without the user's explicit go-ahead.
