"""
ESCARGOT runner adapted for the coking domain.
Directly constructs the Controller with custom components instead of
using the Escargot class, for cleaner integration.
"""
import sys
import logging
import threading
from pathlib import Path

from .. import config

_escargot_available = False
try:
    sys.path.insert(0, str(config.ESCARGOT_DIR))
    from escargot.controller.controller import Controller
    from escargot.operations import operations
    from escargot.parser.parser import ESCARGOTParser
    from escargot.coder.coder import Coder
    from .deepseek_lm import DeepSeekLM
    from .coking_prompter import CokingPrompter
    _escargot_available = True
except ImportError as e:
    logging.getLogger("escargot.coking").warning(f"ESCARGOT not available: {e}")


def run_escargot_reasoning(
    question: str,
    answer_type: str = "natural",
    num_strategies: int = 3,
    timeout: int | None = None,
) -> str:
    """
    Run ESCARGOT Graph of Thoughts reasoning on a question.

    Args:
        question: The question to reason about (can be Chinese or English).
        answer_type: 'natural' for text answer, 'array' for structured data.
        num_strategies: Number of reasoning paths to explore.
        timeout: Maximum execution time in seconds.

    Returns:
        The reasoning result as a string, or error message.
    """
    if not _escargot_available:
        return ""

    timeout = timeout or config.ESCARGOT_TIMEOUT
    logger = logging.getLogger("escargot.coking")

    # Create components
    lm = DeepSeekLM(logger=logger)
    prompter = CokingPrompter(lm=lm, logger=logger)
    parser = ESCARGOTParser(logger)
    coder = Coder()

    # Build initial graph of operations
    operations_graph = operations.GraphOfOperations()
    instruction_node = operations.Generate(1, 1)
    operations_graph.append_operation(instruction_node)

    # Initial thought state
    initial_state = {
        "question": question,
        "input": "",
        "phase": "planning",
        "method": "got",
        "num_branches_response": num_strategies,
        "answer_type": answer_type,
    }

    # Create cancellation event for timeout
    cancellation_event = threading.Event()

    # Create controller
    ctrl = Controller(
        lm,
        operations_graph,
        prompter,
        parser,
        logger,
        coder,
        initial_state,
        cancellation_event=cancellation_event,
        max_tokens=config.ESCARGOT_MAX_TOKENS,
    )
    ctrl.max_run_tries = 2

    # Run with timeout using a thread
    result_container = []
    exception_container = []

    def worker():
        try:
            ctrl.run()
            if ctrl.final_thought is not None:
                if answer_type == "natural":
                    result_container.append(ctrl.final_thought.state.get("input", ""))
                else:
                    output = list(ctrl.coder.step_output.values())[-1] if ctrl.coder.step_output else ""
                    result_container.append(str(output))
            else:
                result_container.append("")
        except Exception as e:
            exception_container.append(e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        cancellation_event.set()
        thread.join(timeout=5)
        return f"ESCARGOT推理超时（{timeout}秒）。将使用基础RAG回答。"

    if exception_container:
        logger.error(f"ESCARGOT error: {exception_container[0]}")
        return ""

    return result_container[0] if result_container else ""
