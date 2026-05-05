"""Token Economy Verifier — webapp prototype.

A minimal Flask app that walks the user through the Roadmap docx
questionnaire, runs the verifier on the resulting TE-IR, and renders
the Report with full explanatory surfaces (why-we-ask, why-it-matters,
critical values, recommendations, mechanism mappings, coherence
issues).

The app's design priority is **explainability**: every input shows
why the question is being asked and which failure mode it feeds; the
verdict renders the formal condition, plain-English explanation,
critical-value math, and concrete redesign recommendations side by
side.
"""
