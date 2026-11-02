# atharva-site

The current profile is `index.html`. Its resume link points to
`Atharva_Pathak_Resume_2026.pdf`.

## Legacy URLs

- `AtharvaCV.pdf` is an identical compatibility copy of the current resume.
  Whenever the current resume is replaced, refresh this copy in the same commit:
  `cp Atharva_Pathak_Resume_2026.pdf AtharvaCV.pdf`.
  Check with `cmp Atharva_Pathak_Resume_2026.pdf AtharvaCV.pdf`.
- `index - Copy.html` is a minimal redirect to `./index.html`, with a visible
  fallback link and `noindex` metadata. JavaScript preserves query parameters and
  the fragment; without JavaScript, meta refresh still reaches the homepage.
- `index-old` is retired (removed). No current repository page or script links to
  it. Its extensionless URL is deliberately not retained as an HTML redirect,
  because static hosting may serve it as a download instead of HTML. After a
  clean deployment, requests to `/index-old` should return 404.

These changes use ordinary files and do not require server redirect support.
The old PDF and complete backup pages remain in Git history; do not republish
old copies in an archive directory or rewrite history.

## Cleanup baseline and rollback

The cleanup was prepared against commit
`1319a907a0e42f3e220b0df2dccbe920c4d7120a`.

The exact content operations are:

1. Copy `Atharva_Pathak_Resume_2026.pdf` over `AtharvaCV.pdf`.
2. Replace `index - Copy.html` with the redirect document.
3. Remove `index-old` with `git rm -- index-old`.
4. Add this maintenance and rollback documentation to `README.md`.

To inspect a historical page without publishing it:

```sh
git show '1319a907a0e42f3e220b0df2dccbe920c4d7120a:index-old'
```

To roll back after merging, use `git revert <cleanup-commit-sha>` (use the squash
commit SHA for a squash merge). If merged with a merge commit, use
`git revert -m 1 <merge-commit-sha>`. Review and deploy the revert normally; no
force push is needed. Reverting deliberately restores the stale public files.

For selective restoration, create a branch from the current default branch:

```sh
git restore --source=1319a907a0e42f3e220b0df2dccbe920c4d7120a -- AtharvaCV.pdf 'index - Copy.html' index-old
git add -- AtharvaCV.pdf 'index - Copy.html' index-old
git commit -m "Restore legacy profile files"
```

## Verification

At the baseline, a scan of all tracked text files found that only the two backup
pages referenced `AtharvaCV.pdf`; neither backup path was referenced by another
page or script. The three current pages are `index.html`,
`pashan-pospaper.html`, and `pkc_yashada_demo.html`.

Before merging, verify the PDFs match, the old profile text is absent from current
pages, and the redirect target exists. The current homepage and other published
assets are unchanged by this cleanup.

After deployment, check `/AtharvaCV.pdf` and
`/Atharva_Pathak_Resume_2026.pdf` serve identical PDF bytes; visit
`/index%20-%20Copy.html` to confirm it reaches the homepage; and confirm
`/index-old` returns 404. For deployment by copying files to a server, explicitly
remove the deployed `index-old` too: a copy-only upload can leave deleted files
behind. Previously cached copies may persist until cache expiry or purge.
