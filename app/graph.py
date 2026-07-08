from typing import TypedDict
from langgraph.graph import END, StateGraph
from app.agents.critic import critique
from app.agents.router import route
from app.agents.synthesis import synthesize
from app.agents.table_agent import answer_from_tables
from app.agents.text_retriever import retrieve_text
MAX_RETRIES = 2

class GraphState(TypedDict, total=False):
    ticker: str
    question: str
    original_question: str
    route_label: str
    text_results: list
    table_result: dict
    answer: str
    sources: list
    context_used: str
    critique: dict
    retries: int

def node_route(state: GraphState) -> GraphState:
    label = route(state['question'])
    return {**state, 'route_label': label}

def node_retrieve(state: GraphState) -> GraphState:
    text_results = retrieve_text(state['ticker'], state['question'])
    table_result = None
    if state['route_label'] in ('numeric_lookup', 'trend_analysis'):
        table_result = answer_from_tables(state['ticker'], state['question'])
    return {**state, 'text_results': text_results, 'table_result': table_result}

def node_synthesize(state: GraphState) -> GraphState:
    result = synthesize(state['question'], state['text_results'], state.get('table_result'))
    return {**state, **result}

def node_critique(state: GraphState) -> GraphState:
    result = critique(state['question'], state['answer'], state['context_used'])
    return {**state, 'critique': result}

def edge_after_critique(state: GraphState) -> str:
    if state['critique']['passed']:
        return 'end'
    if state.get('retries', 0) >= MAX_RETRIES:
        return 'end'
    return 'retry'

def node_broaden_query(state: GraphState) -> GraphState:
    broadened = f'{state['original_question']} (consider related sections and prior periods too)'
    return {**state, 'question': broadened, 'retries': state.get('retries', 0) + 1}

def build_graph():
    g = StateGraph(GraphState)
    g.add_node('route', node_route)
    g.add_node('retrieve', node_retrieve)
    g.add_node('synthesize', node_synthesize)
    g.add_node('critique', node_critique)
    g.add_node('broaden', node_broaden_query)
    g.set_entry_point('route')
    g.add_edge('route', 'retrieve')
    g.add_edge('retrieve', 'synthesize')
    g.add_edge('synthesize', 'critique')
    g.add_conditional_edges('critique', edge_after_critique, {'end': END, 'retry': 'broaden'})
    g.add_edge('broaden', 'route')
    return g.compile()

def ask(ticker: str, question: str) -> dict:
    graph = build_graph()
    initial: GraphState = {'ticker': ticker, 'question': question, 'original_question': question, 'retries': 0}
    final_state = graph.invoke(initial)
    return {'answer': final_state['answer'], 'sources': final_state['sources'], 'route': final_state['route_label'], 'critique': final_state['critique'], 'retries': final_state['retries']}