This dataset is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0).

The experiential_knowledge_41.json dataset contains 41 knowledge entries (identifiers ek_0000 through ek_0040), each representing a distinct piece of offensive security experiential knowledge. Each entry includes: (a)metadata fields (identifier, title, category), (b) core knowledge describing a vulnerability principle or attack technique, (c) application boundaries specifying trigger conditions and applicability scope, (d) an abstracted pattern with
logical formalization (IF. . . THEN. . . ) and generalization direction, (e) operational guidance including pitfalls, chain potential, confidence level, and shelf-life estimate, and
(f) provenance information. Entries span five knowledge categories: chain_pattern (n = 12), signal_interpretation (n = 14), tactical_priority (n = 8), bypass_technique
(n= 6), and pitfall (n= 1).

The quality_metrics.json dataset provides a normative quality assessment of all 41 entries across eight binary dimensions:
1) Trigger Situation First (TSF): Whether the trigger condition describes a situation rather than an action directive.
2) No Action in Knowledge: Whether the core knowledge avoids imperative instructions.
3) Generalizes To: Whether the entry provides a valid generalization direction.
4) Pitfalls Present: Whether pitfall warnings are included.
5) Confidence Rationale: Whether the confidence level is supported by a rationale.
6) Applicable Two-Layer: Whether applicability is specified at both specific and general levels.
7) Abstraction Distance: Whether the abstracted pattern maintains appropriate distance from the concrete instance.
8) Cross-References: Whether cross-references to related entries exist.
The dataset also provides aggregate quality indicators at the repository level: average derivability (0.443), average condition richness (0.771), and average abstraction quality (0.284).

The cross_references.json dataset defines directed relationships among knowledge entries through
complementary pairs and suggested attack chains. Each edge represents a logical succession (e.g., a signal interpretation feeding into a bypass technique), with the full topology extending to ek_0253. For this study, we extract the subgraph restricted to the 41 quality-assessed nodes.

