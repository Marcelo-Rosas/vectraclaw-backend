"""Orquestrador LangGraph para criação de SIPOC com padrão Maker-Checker.

Este módulo implementa um fluxo iterativo de geração e validação de SIPOC
utilizando LangGraph. O padrão arquitetural adotado é:

    Supervisor -> Executor (Maker) -> Checker
         ^                              |
         |____________revise____________|
         |
    human_fallback (após 3 iterações)

Responsabilidades:
- **supervisor**: gatekeeper do loop. Decide entre continuar iterando ou
  encaminhar para fallback humano quando o limite de iterações é atingido.
- **executor (maker)**: gera a proposta de SIPOC/5W2H com base no estado
  atual, incorporando feedbacks anteriores do checker quando disponíveis.
- **checker**: valida a proposta do maker e emite veredicto `accept` ou
  `revise`, opcionalmente com correções estruturadas.
- **human_fallback**: último recurso do sistema. Após 3 tentativas
  malsucedidas, devolve uma correção padronizada solicitando revisão
  humana, evitando loops infinitos e garantindo uma saída graciosa.

O estado (`FlowState`) é o contrato central do fluxo. Todos os nós
recebem o estado completo e retornam um *partial state update* que o
LangGraph mergeia automaticamente.
"""

from __future__ import annotations

import operator
import logging
from typing import Annotated, Any, Dict, List, NotRequired, Optional, Sequence, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph

logger = logging.getLogger("OracleFlow")

# ---------------------------------------------------------------------------
# Constantes de domínio
# ---------------------------------------------------------------------------

# Veredictos possíveis emitidos pelo checker.
VEREDICT_ACCEPT = "accept"
VEREDICT_REVISE = "revise"

# Nomes dos nós no grafo. Usados para rastreamento (logs/métricas) e
# para tornar o código menos dependente de strings mágicas.
NODE_SUPERVISOR = "supervisor"
NODE_EXECUTOR = "executor"
NODE_CHECKER = "checker"
NODE_HUMAN_FALLBACK = "human_fallback"

# Limite máximo de iterações maker-checker antes de acionar o fallback.
MAX_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Contratos de estado
# ---------------------------------------------------------------------------

class FlowState(TypedDict):
    """Estado compartilhado entre todos os nós do grafo SIPOC.

    Esse TypedDict define o contrato de dados do fluxo. Campos anotados
    com ``Annotated[..., operator.add]`` (ex: ``messages``) são acumulados
    pelo LangGraph ao invés de sobrescritos.

    Campos de domínio:
        session_id: Identificador único da sessão de conversação.
        process_id: Identificador opcional do processo em edição.
        domain: Domínio/contexto do processo (ex: "logística").
        user_profile: Perfil do usuário para adaptação de tom:
            "beginner" | "advanced" | "pmo".

    Campos de coleta:
        messages: Histórico de mensagens LangChain. Acumulativo.
        sipoc_snapshot: Estado atual do SIPOC sendo construído.
        collected_5w2h: Dicionário de respostas 5W2H já coletadas.
        current_stage: Etapa atual do diálogo (ex: "collect_5w2h").
        current_event: Evento/disparo atual do processo.
        current_w2h_field: Campo 5W2H em foco, se houver.
        pending_activity: Atividade pendente de confirmação/ajuste.
        last_user_message: Última mensagem recebida do usuário.

    Campos de execução maker-checker:
        maker_response_text: Resposta em texto livre do maker.
        maker_structured: Resposta estruturada do maker (JSON/dict).
        checker_verdict: Veredicto do checker: ``"accept"`` ou ``"revise"``.
        checker_feedback: Feedback textual do checker para o maker.
        checker_corrections: Lista de correções estruturadas.

    Campos de controle:
        iteration_count: Contador de iterações maker-checker já
            executadas. Incrementado pelo supervisor a cada volta no loop.
        current_node: Nome do último nó executado. Usado **apenas**
            para rastreamento, observabilidade e debug. O controle de
            fluxo efetivo é feito pelas funções de roteamento do
            LangGraph e pela constante ``END``.
        previous_feedback: (opcional) Feedback do checker da iteração
            anterior. Injetado no estado para garantir que o maker
            tenha acesso explícito ao histórico de revisões.
    """

    session_id: str
    process_id: Optional[str]
    domain: str
    user_profile: str  # beginner | advanced | pmo

    messages: Annotated[Sequence[BaseMessage], operator.add]

    sipoc_snapshot: Dict[str, Any]
    collected_5w2h: Dict[str, Dict[str, str]]
    current_stage: str
    current_event: str
    current_w2h_field: Optional[str]
    pending_activity: Optional[Dict[str, Any]]
    last_user_message: Optional[str]

    maker_response_text: str
    maker_structured: Dict[str, Any]

    checker_verdict: str  # accept | revise
    checker_feedback: str
    checker_corrections: List[Dict[str, Any]]

    iteration_count: int
    current_node: str

    # Campo auxiliar para garantir que o maker receba o feedback anterior
    # de forma explícita, facilitando testes e rastreabilidade.
    previous_feedback: NotRequired[Optional[str]]


class SupervisorUpdate(TypedDict):
    """Update retornado pelo nó supervisor."""

    current_node: str
    iteration_count: int


class HumanFallbackUpdate(TypedDict):
    """Update retornado pelo nó de fallback humano."""

    checker_corrections: List[Dict[str, Any]]
    current_node: str


# ---------------------------------------------------------------------------
# Factory de estado
# ---------------------------------------------------------------------------

def build_initial_flow_state(
    session_id: str,
    user_message: str,
    *,
    process_id: Optional[str] = None,
    domain: str = "Processo",
    user_profile: str = "advanced",
    current_stage: str = "idle",
    current_event: str = "meta_input",
    current_w2h_field: Optional[str] = None,
    pending_activity: Optional[Dict[str, Any]] = None,
    sipoc_snapshot: Optional[Dict[str, Any]] = None,
    collected_5w2h: Optional[Dict[str, Dict[str, str]]] = None,
    messages: Optional[Sequence[BaseMessage]] = None,
) -> FlowState:
    """Constrói um ``FlowState`` inicial válido e completo.

    Essa factory garante que todos os campos obrigatórios do contrato
    estejam presentes com valores defaults seguros, evitando erros de
    ``KeyError`` durante a execução dos nós.

    Args:
        session_id: Identificador único da sessão (obrigatório).
        user_message: Última mensagem do usuário.
        process_id: Identificador opcional do processo.
        domain: Domínio do processo.
        user_profile: Perfil do usuário ("beginner", "advanced", "pmo").
        current_stage: Etapa atual do diálogo.
        current_event: Evento/disparo atual.
        current_w2h_field: Campo 5W2H em foco, se houver.
        pending_activity: Atividade pendente de confirmação.
        sipoc_snapshot: Estado inicial do SIPOC.
        collected_5w2h: Respostas 5W2H já coletadas.
        messages: Mensagens iniciais do LangChain.

    Returns:
        Instância válida de ``FlowState`` pronta para ser passada ao
        orquestrador.
    """
    from langchain_core.messages import HumanMessage

    initial_messages: Sequence[BaseMessage] = messages or [HumanMessage(content=user_message)]

    return FlowState(
        session_id=session_id,
        process_id=process_id,
        domain=domain,
        user_profile=user_profile,
        messages=initial_messages,
        sipoc_snapshot=sipoc_snapshot or {},
        collected_5w2h=collected_5w2h or {},
        current_stage=current_stage,
        current_event=current_event,
        current_w2h_field=current_w2h_field,
        pending_activity=pending_activity,
        last_user_message=user_message or None,
        maker_response_text="",
        maker_structured={},
        checker_verdict=VEREDICT_ACCEPT,
        checker_feedback="",
        checker_corrections=[],
        iteration_count=0,
        current_node=NODE_SUPERVISOR,
    )


# ---------------------------------------------------------------------------
# Nós do grafo
# ---------------------------------------------------------------------------

async def supervisor_node(state: FlowState) -> SupervisorUpdate:
    """Decide se o fluxo continua iterando ou vai para fallback humano.

    O supervisor atua como *circuit breaker*: a cada passagem ele
    incrementa ``iteration_count``. Se o limite ``MAX_ITERATIONS`` for
    atingido, desvia para ``NODE_HUMAN_FALLBACK``; caso contrário,
    autoriza nova execução do maker através de ``NODE_EXECUTOR``.

    Args:
        state: Estado atual do fluxo.

    Returns:
        Partial update contendo o próximo nó desejado e o contador
        de iterações atualizado.
    """
    previous_iterations = state.get("iteration_count", 0)
    next_iteration = previous_iterations + 1

    logger.info(
        "oracle.flow.supervisor_decided session=%s previous_iteration=%d next_iteration=%d",
        state.get("session_id"),
        previous_iterations,
        next_iteration,
    )

    if next_iteration > MAX_ITERATIONS:
        logger.warning(
            "oracle.flow.max_iterations_reached session=%s max=%d",
            state.get("session_id"),
            MAX_ITERATIONS,
        )
        return SupervisorUpdate(current_node=NODE_HUMAN_FALLBACK, iteration_count=next_iteration)

    return SupervisorUpdate(current_node=NODE_EXECUTOR, iteration_count=next_iteration)


async def executor_node(state: FlowState) -> Dict[str, Any]:
    """Executa o maker para gerar uma proposta de SIPOC/5W2H.

    Importa ``run_maker`` de forma lazy para evitar import circular e
    reduzir o tempo de startup do módulo de orquestração.

    Antes de chamar o maker, garante que o feedback da iteração anterior
    esteja disponível no estado através da chave ``previous_feedback``.
    Isso permite que o prompt do maker evolua a cada revisão.

    Args:
        state: Estado atual do fluxo.

    Returns:
        Resultado do maker (tipicamente contendo ``maker_response_text``,
        ``maker_structured`` e metadados).
    """
    from src.agents.oracle_maker import run_maker

    session_id = state.get("session_id")
    current_event = state.get("current_event")
    iteration_count = state.get("iteration_count", 0)

    logger.info(
        "oracle.flow.maker_started session=%s event=%s iteration=%d",
        session_id,
        current_event,
        iteration_count,
    )

    # Preserva o feedback do checker anterior no estado para o maker.
    # Essa chave é idempotente: se o checker ainda não rodou,
    # previous_feedback será None e o maker tratá-lo como primeira
    # tentativa.
    state["previous_feedback"] = state.get("checker_feedback") or None

    result = await run_maker(state)

    logger.info("oracle.flow.maker_done session=%s", session_id)
    return result


async def checker_node(state: FlowState) -> Dict[str, Any]:
    """Executa o checker para validar a proposta do maker.

    Importa ``run_checker`` de forma lazy pelos mesmos motivos do maker.
    Após a validação, loga o veredicto. Se o checker pedir revisão
    (``revise``), o grafo direciona de volta para o supervisor,
    iniciando uma nova iteração.

    Args:
        state: Estado atual do fluxo.

    Returns:
        Resultado do checker (tipicamente contendo ``checker_verdict``,
        ``checker_feedback`` e ``checker_corrections``).
    """
    from src.agents.oracle_checker import run_checker

    session_id = state.get("session_id")

    result = await run_checker(state)
    verdict = result.get("checker_verdict", VEREDICT_ACCEPT)
    feedback = result.get("checker_feedback", "")

    logger.info(
        "oracle.flow.checker_verdict session=%s verdict=%s feedback=%.200s",
        session_id,
        verdict,
        feedback,
    )

    if verdict == VEREDICT_REVISE:
        logger.info(
            "oracle.flow.iteration_loop session=%s iteration=%d",
            session_id,
            state.get("iteration_count", 0),
        )

    return result


async def human_fallback_node(state: FlowState) -> HumanFallbackUpdate:
    """Fallback humano após esgotar as tentativas automáticas.

    Quando o supervisor detecta que ``MAX_ITERATIONS`` foi ultrapassado,
    esse nó é acionado. Ele não tenta mais gerar conteúdo; em vez disso,
    devolve uma correção padronizada solicitando intervenção humana.

    A chave ``current_node`` aqui é **apenas informativa** para logs e
    telemetria. A transição de fato para o fim do grafo é controlada
    pela edge ``add_edge(NODE_HUMAN_FALLBACK, END)``.

    Args:
        state: Estado atual do fluxo.

    Returns:
        Update contendo a correção estruturada e metadados de encerramento.
    """
    feedback = (
        state.get("checker_feedback")
        or "Oracle não conseguiu gerar resposta satisfatória após 3 tentativas."
    )

    logger.warning(
        "oracle.flow.human_fallback session=%s iteration=%d feedback=%.200s",
        state.get("session_id"),
        state.get("iteration_count", 0),
        feedback,
    )

    return HumanFallbackUpdate(
        checker_corrections=[
            {
                "type": "requires_human_review",
                "reason": feedback,
                "suggested_question": (
                    "Por favor, reformule ou detalhe melhor a informação que deseja registrar."
                ),
            }
        ],
        current_node=NODE_HUMAN_FALLBACK,
    )


# ---------------------------------------------------------------------------
# Funções de roteamento
# ---------------------------------------------------------------------------

def _route_after_supervisor(state: FlowState) -> str:
    """Roteia o fluxo após o supervisor.

    O supervisor decide qual nó será executado através do campo
    ``current_node``, mas essa decisão é apenas uma *recomendação*.
    A função de roteamento traduz essa recomendação em um nome de nó
    válido no grafo.

    Args:
        state: Estado atual do fluxo.

    Returns:
        Nome do próximo nó: ``NODE_HUMAN_FALLBACK`` ou ``NODE_EXECUTOR``.
    """
    next_node = state.get("current_node")
    if next_node == NODE_HUMAN_FALLBACK:
        return NODE_HUMAN_FALLBACK
    return NODE_EXECUTOR


def _route_after_checker(state: FlowState) -> str:
    """Roteia o fluxo após o checker.

    Se o checker aceitou a proposta, encerra o fluxo com ``END``.
    Caso contrário, retorna ao supervisor para uma nova iteração.

    Args:
        state: Estado atual do fluxo.

    Returns:
        ``END`` se o veredicto for ``accept``; ``NODE_SUPERVISOR`` se
        for ``revise``.
    """
    verdict = state.get("checker_verdict", VEREDICT_ACCEPT)
    if verdict == VEREDICT_ACCEPT:
        return END
    return NODE_SUPERVISOR


# ---------------------------------------------------------------------------
# Factory / Singleton
# ---------------------------------------------------------------------------

_ORCHESTRATOR: Any | None = None


def build_orchestrator() -> Any:
    """Monta e compila o grafo LangGraph do fluxo SIPOC.

    Essa função é uma *factory* pura: cada chamada cria uma nova
    instância do grafo. Para a maioria dos casos de uso, prefira
    ``get_orchestrator()``, que mantém uma única instância em
    memória e evita recompilações desnecessárias.

    Estrutura do grafo:

        ENTRY -> supervisor
        supervisor -> executor   (se ainda houver iterações)
        supervisor -> human_fallback (se MAX_ITERATIONS excedido)
        executor -> checker
        checker -> END           (se accept)
        checker -> supervisor    (se revise)
        human_fallback -> END

    Returns:
        Grafo compilado do LangGraph pronto para invocação.
    """
    workflow = StateGraph(FlowState)

    workflow.add_node(NODE_SUPERVISOR, supervisor_node)
    workflow.add_node(NODE_EXECUTOR, executor_node)
    workflow.add_node(NODE_CHECKER, checker_node)
    workflow.add_node(NODE_HUMAN_FALLBACK, human_fallback_node)

    workflow.set_entry_point(NODE_SUPERVISOR)
    workflow.add_conditional_edges(NODE_SUPERVISOR, _route_after_supervisor)
    workflow.add_edge(NODE_EXECUTOR, NODE_CHECKER)
    workflow.add_conditional_edges(NODE_CHECKER, _route_after_checker)
    workflow.add_edge(NODE_HUMAN_FALLBACK, END)

    return workflow.compile()


def get_orchestrator() -> Any:
    """Retorna a instância singleton do orquestrador.

    O grafo LangGraph é compilado na primeira chamada e reutilizado
    nas chamadas subsequentes. Isso reduz a latência de inicialização
    em servidores de longa duração (ex: Cloud Run).

    Nota: se você precisar de múltiplas configurações de grafo em
    paralelo (testes unitários, multi-tenant), use ``build_orchestrator()``
    diretamente ao invés desta função.

    Returns:
        Instância compilada e cacheada do grafo SIPOC.
    """
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = build_orchestrator()
    return _ORCHESTRATOR
