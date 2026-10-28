# Contributor and commit rules

- Use the configured human Git author and committer identity. Preserve genuine
  human authorship, co-authorship, acknowledgements and legally required notices.
- Do not add tools, AI agents, models or automation as authors/co-authors,
  signatories or reviewers. Do not add generated-with, powered-by or similar
  advertising footers to commits or pull requests. Technical discussion of a tool
  is fine; contributor credit is for people.
- Preserve Tahir Masood's (`tahirmasood2`) authorship and README acknowledgement.
- Install the repository's local commit guard once per checkout:

  ```sh
  git config --local core.hooksPath .githooks
  ```

  It requires `python3`, rejects common bot attribution without modifying the
  message, and permits human co-authors and sign-offs. Do not bypass it to add
  automated credit. See DEVELOPMENT.md for testing and limitations.
- Do not rewrite history or published release tags without the owner's explicit
  authorization. Published installers and their original source tags are separate
  from later maintenance of `main`.
