---
description: "Use when adding or correcting Google-style docstrings in Python modules."
argument-hint: "Python file, module, or selection to document"
agent: "agent"
---
Inspect the current Python file, module, or selected code and ensure Google-style docstrings are complete and correct from top to bottom.

Requirements:
- Audit all existing docstrings in scope for correctness and completeness, then fix any inaccuracies.
- Add concise, accurate docstrings to public classes, functions, and methods that are missing them.
- Correct outdated, misleading, or contradictory docstrings (summary text, args, returns, raises, yields, and examples) so they match the current implementation.
- Ensure parameter names, defaults, nullability, and types described in docstrings match the current function/method signatures.
- Ensure `Returns:`, `Yields:`, and `Raises:` sections reflect actual behavior; remove sections that do not apply and add missing ones that do.
- Ensure docstrings describe observable behavior and contracts, not guessed intent.
- Preserve existing behavior and avoid unrelated refactors.
- Include an `Examples:` section for public classes only.
- In class docstrings, `Examples:` must focus on class instantiation (construction) and not method behavior.
- For non-dataclass classes, include constructor arguments in the class docstring under `Args:` when the constructor defines the initialization contract.
- For dataclasses, document fields under `Attributes:` only, and do not add an `Args:` section.
- Do not add a docstring to `__init__` when the constructor contract is already documented on the class.
- Include `Attributes:` in class docstrings for dataclasses.
- Include `Attributes:` in class docstrings for non-dataclasses when the class has public attributes that are not documented in the constructor or elsewhere.
- Include `Args:`, `Returns:`, `Yields:`, and `Raises:` sections where they apply.
- Document private methods with a single line description under the method signature.
- Do not document private attributes in `Attributes:` sections.
- Match the repository's existing style and linter expectations.
- Clean up any docstring-related whitespace or formatting issues introduced during the edit.
- Validate the edited file and fix any diagnostics caused by the change.

When responding:
- Make the code changes directly.
- Keep the patch minimal.
- Summarize what was documented and note any remaining issues if validation fails.
