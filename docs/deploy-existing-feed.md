# Keep an existing public podcast while cleaning the source

The source tree contains generic code. Your source list and per-source options are held in repository secrets. Pages continues serving the same RSS URL and MP3 paths.

1. Pause the old daily workflow and wait for any active run to finish. Back up the publication list and `gh-pages` privately.
2. Under Settings → Secrets and variables → Actions, add a **secret** named `PUBLICATIONS` containing the current `publications.txt` contents. Retain `GEMINI_API_KEY` and any optional login cookie. If using a cookie, add exact allowed hostnames in the `SUBSTACK_AUTH_HOSTS` secret.
3. Install the cleaned dependencies locally and generate a random state key:

   ```sh
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Save the result as the `STATE_ENCRYPTION_KEY` secret and back it up privately. Do not store it in source, issues, logs or repository variables.

4. Add **variables** `PUBLISH_TO_PAGES=true` and `KEEP_EPISODES=0`. Set the desired `EPISODE_MODE` and `MAX_EPISODE_MINUTES`, or let per-source options in the secret override the global mode. Leave `FEED_TITLE` unset to preserve the old feed name.
5. Put the cleaned source on `main`. Keep the existing `gh-pages` branch and the existing Pages source configuration. Do not push a mirror or delete that branch.
6. Manually run **Newsletter podcast**. The workflow first downloads the existing site, imports old processing state, preserves episode GUIDs/audio links/notes/dates and completed-post IDs, then creates new episodes. The plaintext old `state.json` is removed from current Pages output; the new processing state is encrypted.
7. Verify the same RSS URL and an old audio enclosure in your podcast app. Set `ENABLE_AUTOMATION=true` and re-enable the workflow for daily runs.

`KEEP_EPISODES=0` retains all episodes. Positive values intentionally prune old articles. A fetch failure or concurrent change to the published branch aborts the update rather than replacing the feed with stale or empty output.

Public RSS and MP3s continue revealing what you read, by design. Current source files and output no longer contain the plaintext subscription configuration. Old source commits can still contain `publications.txt`; rewriting affected `main` history is separate from preserving `gh-pages`. Old logs, refs and third-party copies can also retain earlier disclosures.

Keep the state key unchanged across deployments. A wrong key or tampered ciphertext fails the run rather than resetting completed history. When restoring old backups, restore the matching encryption key too.
