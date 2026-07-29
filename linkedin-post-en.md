# One-paragraph share post

Use the @ mention so it actually tags him: type "@Ismael Faro" and pick him from
LinkedIn's dropdown rather than pasting the name as plain text.

Suggested image: docs/img/alignment.png (the 59-of-60 identical residues). It is
the most arresting thing in the piece and it stops the scroll. docs/img/hero.png
is the safer, more corporate alternative.

---

I took Ismael Faro's nanoLoop — a small autonomous engineering harness built for
frontier models — and rebuilt it around Gemma 4 12B running entirely on a fanless
MacBook Air: no cloud, no API key, no account anywhere. It gets further than I
expected, and the reason turned out to be architectural rather than clever
prompting: bind fewer tools per phase, make the plan typed JSON that code
iterates, let a linter and a test suite decide what "done" means, and never let
the model rewrite a whole file. I put it through two problems I genuinely enjoyed
— shortening quantum circuits, where unitary equivalence gives you a
mathematically exact oracle, and the 2001 fly's-eye experiment, where a fly gene
called eyeless and a human eye condition called aniridia share no letters in
their names and 133 consecutive residues at 93% identity in their sequences. It
is Apache-2.0 and published as an experiment rather than a tool, so I would
honestly rather hear where it falls over than where it works.

---

## Shorter variant, if the above runs long in the preview

I rebuilt Ismael Faro's nanoLoop — an autonomous engineering harness designed for
frontier models — around Gemma 4 12B running entirely on a fanless laptop, with
no cloud and no API key. What made it work was subtraction rather than prompting:
fewer tools per phase, a typed plan that code iterates, a test suite deciding
what "done" means, and a model that never rewrites a whole file. I tested it on
quantum circuit optimisation and on the 2001 fly's-eye experiment, where a fly
gene and a human eye disease share no letters in their names and 133 residues at
93% identity in their sequences. Apache-2.0, published as an experiment, and I
would rather hear where it breaks than where it works.
