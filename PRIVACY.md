# Privacy and existing installations

The shareable repository should contain code and synthetic examples. Keep personal publications in an ignored `publications.txt`, a local `.env`, or repository Actions secrets, including in a public repository. The program does not discover account subscriptions.

The project landing page offers an article-to-audio preview and the original sample: it does not include personal episode metadata, a personal feed title or a personal RSS link. The generated RSS feed and audio remain reachable directly through GitHub Pages and identify sources. A secret publication list does not make the output private. Neither `itunes:block` nor an unguessable URL is an access control. GitHub Pages publishing is an explicit public-content choice. It is supported for a personal podcast whose owner wants private configuration and public audio. Use a private installation with authenticated hosting when the audio itself should be private.

The optional live demo sends the entered public article URL or pasted text to its preview backend, and the selected opening text to Microsoft's Edge TTS service. It uses no subscription login cookies, Gemini credentials or personal processing state. Temporary audio is deleted after each request, and the MP3 is returned directly to the browser rather than published or added to RSS. Downloading retains a copy on the user's device. The app disables access logging; hosting infrastructure may have its own logs. Rate limits retain client addresses in process memory for up to ten minutes. Use a separate backend deployment without personal pipeline secrets.

Public full narrations redistribute the source writing as audio and include article text in RSS descriptions. Access, a paid subscription, and attribution alone do not grant redistribution rights; publishing without those rights can lead to copyright complaints and takedown notices. Prefer the default summary mode for public feeds, review summaries for original wording and limited quotations, and retain source links. Per-source `full` options override that default. Summaries do not guarantee permission to publish, and changing modes does not remove existing full episodes or descriptions.

For scheduled personal listening, use a private repository with `PUBLISH_TO_PAGES` unset or `false`, then host the generated feed and MP3s behind authentication supported by your podcast app or on a reachable private network. Protect audio URLs as well as the feed. An unguessable path only limits discovery; anyone with the URL can access and share it. See [Keep your personal feed private](README.md#keep-your-personal-feed-private) for the Actions and hosting steps. Private hosting does not grant rights to access or convert source content.

## Data locations

| Location | Contents | Handling |
| --- | --- | --- |
| `publications.txt`, `.env` | Source choices and credentials | Ignored by Git; never publish. |
| `.state/state.json` | Completed IDs, episodes, retry payloads and source configuration | Outside `site/`; never serve. Private Actions caches are accessible to people with repository access. |
| `site/podcast-state.enc` | Encrypted processing state and retry payloads | Public ciphertext authenticated and encrypted with the secret `STATE_ENCRYPTION_KEY`. Do not commit or expose the key. |
| `site/feed.xml`, `site/episodes/` | Source titles, URLs, audio and full-narration article text | Share only as intended; public hosting reveals your reading choices. |
| Workflow logs | Progress and sanitized failure types | Source titles are disabled by default. Public workflow logs are visible. |
| Gemini | Article text sent for summaries | Review provider data-use terms and account settings. Full narration does not send text to Gemini. |
| Edge TTS | Narration text sent for audio generation | Applies to both modes. |

Login cookies are sent only to the explicitly configured HTTPS host allowlist. Do not enable a cookie for third-party RSS hosts. This prevents accidental forwarding, but does not make a compromised allowed host safe.

## Migrating a repository that already exposed personal sources

Deleting a tracked list in a new commit does **not** remove it from Git history. Existing `gh-pages` output, workflow logs, artifacts, caches, forks and clones can retain identifying material.

Before announcing a previously personal repository:

1. Make a private backup of the source list, credentials, processing state and episodes you want to keep. Do not paste them into an issue or pull request.
2. If keeping public audio, retain `gh-pages`, use a `PUBLICATIONS` secret and a `STATE_ENCRYPTION_KEY` secret, and follow the existing-feed upgrade guide. The importer preserves old episode identities and completed-post IDs. If making the audio private, set up private hosting separately.
3. Pause the old workflow during the upgrade. Confirm that the shared source tree contains only generic examples, and that per-source configuration comes from secrets.
4. Keep the public feed and audio if they are intentionally public. Removing `gh-pages` breaks its RSS/audio links; it is not required just to make subscription configuration private.
5. If rewriting history, coordinate with collaborators, remove personal files from all affected branches/tags, and have collaborators make fresh clones. A normal PR or squash merge is insufficient.
6. Review old Actions logs, artifacts and caches. GitHub may retain commits referenced by PRs and cached pages; consult [GitHub's removal guide](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

History rewriting and feed removal are separate destructive operations. No cleanup can erase copies that other people already downloaded. These code changes prevent new accidental disclosure; they do not claim to erase historical exposure.


