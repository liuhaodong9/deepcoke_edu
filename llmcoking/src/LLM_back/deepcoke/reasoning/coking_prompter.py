"""
Coking domain prompter for ESCARGOT reasoning.
Replaces the biomedical domain prompts with coal coking domain prompts.
"""
import sys
import re
import logging
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(r"D:\escargot")))

from ..knowledge_graph.schema import NODE_TYPES, RELATIONSHIP_TYPES_STR, CYPHER_SCHEMA


class CokingPrompter:
    """
    Domain-specific prompter for ESCARGOT reasoning in the coking domain.
    Replaces ESCARGOTPrompter's biomedical prompts with coking domain prompts.
    """

    planning_prompt = """You are a brilliant strategic thinker with access to a coal coking knowledge base. You will receive a question about coal blending, coking, or related topics. The knowledge base is built from academic papers and a knowledge graph. You will break down the question into clear steps.

The knowledge graph contains the following node types: {node_types}.
The knowledge graph contains the following relationships: {relationship_types}.

Only show the steps you will take and a small description for each step. If you can determine the knowledge graph relationship that can provide insight in the step, provide the relationship and the specific node name.
Each step MUST be clear on what the knowledge request output should be.

Examples:
Question: What factors affect CSR in coal blending?
Step 1: Find concepts related to CSR (Coke Strength after Reaction).
Relationship: STUDIES_CONCEPT
Node: CSR
Step 2: Find papers that study CSR and identify the factors mentioned.
Relationship: MEASURES_PROPERTY
Node: CSR
Step 3: Summarize the key factors affecting CSR from the retrieved knowledge.

Question: Compare FTIR and NMR methods for characterizing coal structure
Step 1: Find papers that use FTIR method.
Relationship: USES_METHOD
Node: FTIR
Step 2: Find papers that use NMR method.
Relationship: USES_METHOD
Node: NMR
Step 3: Find what properties each method characterizes.
Relationship: CHARACTERIZES
Step 4: Compare the two methods based on characterized properties and paper findings.

Question: How does vitrinite reflectance affect coke quality?
Step 1: Find concepts related to vitrinite reflectance.
Relationship: STUDIES_CONCEPT
Node: vitrinite reflectance
Step 2: Find properties measured in relation to vitrinite reflectance.
Relationship: MEASURES_PROPERTY, RELATED_TO
Step 3: Synthesize the relationship between vitrinite reflectance and coke quality.

Here is your question:
{{question}}

Let's think step by step, and be very succinct, clear, and efficient."""

    plan_assessment_prompt = """You are a strategic thinker with expertise in coal coking science. You will receive a question and a few approaches to answer it using a coking domain knowledge graph.

The knowledge graph contains node types: {node_types}.
The knowledge graph contains relationships: {relationship_types}.

Evaluate each approach and score it from 1 to 10 based on:
1. Clarity: Are the steps clear and unambiguous?
2. Efficiency: Does it minimize redundant knowledge extractions?
3. Specificity: Does it reference specific concepts, methods, or materials?
4. Completeness: Will it produce a comprehensive answer?

Return your assessment in this XML format:
<assessment>
<approach id="1"><score>X</score><reason>...</reason></approach>
<approach id="2"><score>X</score><reason>...</reason></approach>
<approach id="3"><score>X</score><reason>...</reason></approach>
</assessment>

Question: {{question}}

Approaches:
{{approaches}}"""

    python_conversion_prompt = """You are a Python expert. Convert the following reasoning plan into executable Python code.

You have access to a function `knowledge_extract(request)` that queries a coking domain knowledge base.
The request format uses: NodeType-RELATIONSHIP-!specific_value!
Examples:
- knowledge_extract("Paper-STUDIES_CONCEPT-!CSR!") → returns papers studying CSR
- knowledge_extract("Method-CHARACTERIZES-!vitrinite reflectance!") → returns methods characterizing vitrinite reflectance
- knowledge_extract("Material-HAS_PROPERTY-!coal fluidity!") → returns materials with coal fluidity property

You also have `numpy` available.

The code should:
1. Use knowledge_extract() to get data from the knowledge base
2. Process and analyze the data
3. Store the final result in a variable called `result`

Question: {{question}}
Plan: {{plan}}

Write clean, executable Python code:"""

    code_assessment_prompt = """You are a code quality expert for coal science applications. Score each code implementation from 1 to 10.

Criteria:
1. Correctness: Will it produce the right answer?
2. Use of knowledge_extract: Does it properly query the knowledge base?
3. Data processing: Is the analysis logic sound?
4. Robustness: Does it handle empty results?

Return in XML format:
<assessment>
<code id="1"><score>X</score><reason>...</reason></code>
<code id="2"><score>X</score><reason>...</reason></code>
<code id="3"><score>X</score><reason>...</reason></code>
</assessment>

Question: {{question}}
Code implementations:
{{codes}}"""

    xml_conversion_prompt = """Convert the following Python code into a step-by-step execution plan in XML format.

Each step should have:
- StepID: unique identifier
- Instruction: what this step does
- Code: the Python code for this step

Also provide an EdgeList showing dependencies between steps.

Format:
<Plan>
<Steps>
<Step><StepID>1</StepID><Instruction>...</Instruction><Code>...</Code></Step>
</Steps>
<EdgeList>
<Edge><Source>1</Source><Target>2</Target></Edge>
</EdgeList>
</Plan>

Code to convert:
{{code}}"""

    output_prompt = """You are a coal coking domain expert assistant called DeepCoke. Based on the following step-by-step analysis results, provide a comprehensive answer to the question.

Requirements:
1. Answer in Chinese (中文)
2. Be precise and cite specific findings from each step
3. Use Markdown formatting
4. Use $$ for math formulas

Question: {{question}}

Step results:
{{step_outputs}}

Provide your answer:"""

    knowledge_request_adjustment_prompt = """You are adjusting a knowledge request for a coal coking knowledge graph.

The knowledge graph has these node types: {node_types}
And these relationships: {relationship_types}

Original instruction: {{instruction}}
Original code context: {{code}}
Knowledge request: {{request}}

Adjust the request to match the graph schema. Use the format:
NodeType-RELATIONSHIP-!specific_value!

Examples:
- Paper-STUDIES_CONCEPT-!CSR! (find papers about CSR)
- Method-CHARACTERIZES-!porosity! (find methods measuring porosity)
- Material-HAS_PROPERTY-!coal fluidity! (find materials with fluidity data)

Return ONLY the adjusted request."""

    def __init__(self, graph_client=None, vector_db=None, lm=None,
                 node_types=None, relationship_types=None, logger=None):
        self.graph_client = graph_client
        self.vector_db = vector_db
        self.lm = lm
        self.node_types = node_types or NODE_TYPES
        self.relationship_types = relationship_types or RELATIONSHIP_TYPES_STR
        self.logger = logger or logging.getLogger(__name__)

        # Format prompts with node/relationship types
        self.planning_prompt = self.planning_prompt.format(
            node_types=self.node_types,
            relationship_types=self.relationship_types,
        )
        self.plan_assessment_prompt = self.plan_assessment_prompt.format(
            node_types=self.node_types,
            relationship_types=self.relationship_types,
        )
        self.knowledge_request_adjustment_prompt = self.knowledge_request_adjustment_prompt.format(
            node_types=self.node_types,
            relationship_types=self.relationship_types,
        )

    def generate_prompt(self, state: dict, **kwargs) -> str:
        """Generate the appropriate prompt based on the current phase."""
        phase = state.get("phase", "planning")
        question = state.get("question", "")

        if phase == "planning":
            return self.planning_prompt.replace("{question}", question)
        elif phase == "plan_assessment":
            approaches = state.get("input", "")
            prompt = self.plan_assessment_prompt.replace("{question}", question)
            return prompt.replace("{approaches}", approaches)
        elif phase == "python_conversion":
            plan = state.get("input", "")
            prompt = self.python_conversion_prompt.replace("{question}", question)
            return prompt.replace("{plan}", plan)
        elif phase == "code_assessment":
            codes = state.get("input", "")
            prompt = self.code_assessment_prompt.replace("{question}", question)
            return prompt.replace("{codes}", codes)
        elif phase == "xml_conversion":
            code = state.get("input", "")
            return self.xml_conversion_prompt.replace("{code}", code)
        elif phase == "output":
            step_outputs = state.get("input", "")
            prompt = self.output_prompt.replace("{question}", question)
            return prompt.replace("{step_outputs}", step_outputs)
        else:
            return f"Answer this coal coking question: {question}"

    def get_knowledge(self, request: str, instruction: str = "",
                      code: str = "", full_code: str = "") -> str:
        """
        Retrieve knowledge from the coking knowledge graph and vector database.
        This is called by ESCARGOT's Coder when executing knowledge_extract().
        """
        self.logger.info(f"Knowledge request: {request}")

        results = []

        # 1. Try knowledge graph query via Neo4j
        if self.graph_client:
            try:
                kg_results = self._query_kg(request)
                if kg_results:
                    results.extend(kg_results)
            except Exception as e:
                self.logger.warning(f"KG query failed: {e}")

        # 2. Fall back to / also use vector database
        if self.vector_db or not results:
            try:
                vdb_results = self._query_vectordb(request)
                if vdb_results:
                    results.extend(vdb_results)
            except Exception as e:
                self.logger.warning(f"Vector DB query failed: {e}")

        if not results:
            return "No relevant knowledge found for this request."

        return "\n".join(results[:10])

    def _query_kg(self, request: str) -> list[str]:
        """Query the Neo4j knowledge graph."""
        from ..knowledge_graph.neo4j_client import query_kg_with_llm
        results = query_kg_with_llm(request)
        return [str(r) for r in results] if results else []

    def _query_vectordb(self, request: str) -> list[str]:
        """Query the ChromaDB vector database."""
        from ..vectorstore.retriever import retrieve
        chunks = retrieve(request, top_k=5)
        return [
            f"[{c.title} ({c.year})]: {c.text[:500]}"
            for c in chunks
        ]

    def aggregation_prompt(self, state: dict, **kwargs) -> str:
        return self.generate_prompt(state, **kwargs)

    def improve_prompt(self, state: dict, **kwargs) -> str:
        return self.generate_prompt(state, **kwargs)

    def validation_prompt(self, state: dict, **kwargs) -> str:
        return self.generate_prompt(state, **kwargs)

    def score_prompt(self, state: dict, **kwargs) -> str:
        return self.generate_prompt(state, **kwargs)
