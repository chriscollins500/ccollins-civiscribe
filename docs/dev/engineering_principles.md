# CiviScribe engineering principles

Status: Governing project requirement, adopted November 25, 2026.

These principles govern the whole project and every consequential technical
decision. They apply throughout discovery, requirements, architecture,
algorithms, protocols, implementation, tooling, design, capabilities, review,
verification, packaging, release, operation, maintenance, and retirement.

## Maximum technical ambition

Maximum technical ambition is a governing requirement of this project.

Pursue speculative, frontier-expanding R&D, including concepts starting at
TRL 1 where appropriate. Treat current best practice and the current state of
the art as starting points to challenge and exceed.

Apply this ambition across architecture, algorithms, protocols, implementation,
tooling, design, and capabilities. For consequential decisions, investigate the
strongest plausible alternatives, including recent research, experimental
implementations, theoretical approaches, unconventional combinations, and
original methods.

Do not select an approach merely because it is familiar, widely adopted,
mature, or easier to implement. Assess alternatives against the project's
actual goals and constraints.

Uncertainty should trigger investigation and experimentation. The absence of
an existing library, reference implementation, or established development
pattern is not sufficient reason to abandon an approach.

When recommending a more conventional solution, identify the concrete
constraint, evidence, or tradeoff that justifies it. General statements such
as "too experimental," "too complex," or "not standard practice" are
insufficient by themselves.

Carry promising approaches through implementation and meaningful evaluation.
Clearly distinguish demonstrated capability, theoretical support, and
speculative assumptions. Claims of improvement must be supported by evidence.

The objective is working technology that advances what is possible. Explore
aggressively, invent where needed, and be precise about what has actually been
achieved.

## Decision evidence

For consequential decisions, record the following in the relevant design
document or pull request:

1. **Goal and constraints:** the capability to advance, the current baseline,
   and the actual product, interoperability, security, privacy, fidelity,
   resource, and operational constraints that apply.
2. **Strongest plausible alternatives:** research, experimental and theoretical
   approaches, unconventional combinations, and original methods considered;
   explain the evidence behind their inclusion or rejection. For external
   technical evidence, retain primary-source URLs and access dates.
3. **Investigation and implementation:** the unresolved questions, hypotheses,
   experiments, and implemented candidates used to resolve uncertainty.
4. **Meaningful evaluation:** the criteria for success and failure, comparable
   baselines, representative workloads, relevant correctness and failure
   checks, and reproducible commands, environments, and exact artifacts.
5. **Decision and tradeoffs:** the measured outcome and concrete reasons for
   the selection. Justify a conventional choice with applicable constraints or
   evidence; familiarity, maturity, popularity, or implementation convenience
   alone do not justify it.
6. **Limits and follow-through:** remaining assumptions, uncertainties,
   unsuccessful experiments, and the work needed to establish or extend the
   result. Carry promising candidates through implementation and evaluation.

## Capability and improvement claims

Keep the following evidence states explicit in recommendations, design
documents, roadmap work, reviews, and release claims:

| Evidence state | What supports it |
| --- | --- |
| Demonstrated capability | An executed implementation, identified artifacts and environment, and recorded results. State the tested scope and limits. |
| Theoretical support | A derivation, proof, model, or primary research with its assumptions and applicability stated. Record the gap to implementation and evaluation. |
| Speculative assumption | A hypothesis or proposed mechanism, with its uncertainties and the experiment needed to assess it. |

A claim of improvement must identify its baseline, evaluation method,
observed outcome, and limitations. Research or an experiment being complete
does not by itself establish a shipped product capability.

## Product contracts and safeguards

The [product contract](../product_contract.md),
[architecture](../architecture.md), [security policy](../../SECURITY.md),
and [contributor validation requirements](../../CONTRIBUTING.md) supply
concrete acceptance constraints for this work. Pixels-first saving, truthful
resource identity, image fidelity, safe paths, privacy, interoperability, and
preservation of user data apply to experimental implementations as well as
released code.

Evaluate early research using scoped prototypes, synthetic fixtures, and
isolated environments appropriate to the hypothesis. Changes to product scope
or public contracts must be explicit and reviewed. Existing technology
decisions are evidence to reassess when their assumptions change or stronger
approaches become plausible.

Use these principles with the [design authority](../README.md),
[contributor guide](../../CONTRIBUTING.md), and [roadmap](../../ROADMAP.md).
