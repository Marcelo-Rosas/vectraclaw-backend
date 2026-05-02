# Serviço de Análise SIPOC com Sugestões de Automação
# Objetivo: Analisar SIPOC e recomendar workflow de automação + agentes

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import json
from anthropic import Anthropic

# ===================================================================
# Data Models
# ===================================================================

@dataclass
class AutomationScore:
    activity: str
    frequency: str  # daily, weekly, monthly, ad-hoc
    time_spent_minutes: int
    manual_effort_pct: int  # 0-100
    business_value: str  # high, medium, low
    complexity: str  # simple, moderate, complex
    automation_score: float  # 0-100, calculated
    recommendation: str  # "automate", "semi-automate", "keep_manual"

@dataclass
class AgentProposal:
    name: str
    role: str
    activities: List[str]  # Activities this agent would handle
    input_types: List[str]  # What inputs it consumes
    output_types: List[str]  # What outputs it produces
    suggested_model: str  # "claude_code", "webhook", "harness"
    token_budget: int
    max_turns: int
    estimated_time_minutes: int

@dataclass
class RoutineProposal:
    name: str
    trigger: str  # "schedule" or "event"
    schedule_cron: Optional[str]  # For scheduled triggers
    event_trigger: Optional[str]  # For event-based triggers
    agents: List[str]  # Agent IDs/names in sequence
    success_hooks: List[Dict]
    failure_hooks: List[Dict]
    timeout_minutes: int

@dataclass
class AutomationPlan:
    sipoc_process_id: str
    analysis_date: datetime
    total_automation_potential: float  # 0-100
    activities_analyzed: int
    activities_automatable: int
    estimated_time_saved_hours_per_week: float
    estimated_cost_savings_usd_per_month: float
    payback_period_weeks: int

    scores: List[AutomationScore]
    proposed_agents: List[AgentProposal]
    proposed_routines: List[RoutineProposal]
    dependencies: List[Dict[str, str]]  # Dependency graph
    risks: List[str]
    recommendations: List[str]

# ===================================================================
# SIPOC Automation Suggester
# ===================================================================

class SipocAutomationSuggester:
    """
    Analyzes a SIPOC diagram and suggests automation opportunities.
    Uses Claude to generate intelligent recommendations.
    """

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client
        self.client = Anthropic()
        self.model = "claude-opus-4-7"

    async def analyze_sipoc_for_automation(
        self,
        sipoc_process_id: str,
        company_context: Dict[str, Any],
        include_cognee_analysis: bool = True
    ) -> AutomationPlan:
        """
        Main entry point: analyze SIPOC and generate automation plan

        Args:
            sipoc_process_id: UUID of the SIPOC process to analyze
            company_context: {"company": "CFN", "sector": "financeiro", "process": "conciliacao"}
            include_cognee_analysis: Whether to use Cognee for historical context

        Returns:
            AutomationPlan with detailed recommendations
        """

        # 1. Fetch SIPOC data from Supabase
        sipoc_data = await self._fetch_sipoc_data(sipoc_process_id)

        # 2. Use Claude to analyze and score activities
        activity_scores = await self._score_activities_with_claude(sipoc_data, company_context)

        # 3. Generate agent proposals based on automation opportunities
        agent_proposals = self._generate_agent_proposals(activity_scores, sipoc_data)

        # 4. Generate routine proposals (orchestration)
        routine_proposals = self._generate_routine_proposals(agent_proposals, sipoc_data)

        # 5. Calculate ROI and payback
        roi_metrics = self._calculate_roi(activity_scores, agent_proposals)

        # 6. Identify dependencies and risks
        dependencies = self._identify_dependencies(agent_proposals, routine_proposals)
        risks = self._identify_risks(sipoc_data, agent_proposals)

        # 7. Generate final recommendations
        recommendations = self._generate_recommendations(
            sipoc_data,
            activity_scores,
            agent_proposals,
            roi_metrics
        )

        # 8. Persist analysis to database
        plan = AutomationPlan(
            sipoc_process_id=sipoc_process_id,
            analysis_date=datetime.now(),
            total_automation_potential=sum([s.automation_score for s in activity_scores]) / len(activity_scores) if activity_scores else 0,
            activities_analyzed=len(activity_scores),
            activities_automatable=len([s for s in activity_scores if s.automation_score >= 70]),
            estimated_time_saved_hours_per_week=roi_metrics["time_saved_weekly"],
            estimated_cost_savings_usd_per_month=roi_metrics["cost_savings_monthly"],
            payback_period_weeks=roi_metrics["payback_weeks"],
            scores=activity_scores,
            proposed_agents=agent_proposals,
            proposed_routines=routine_proposals,
            dependencies=dependencies,
            risks=risks,
            recommendations=recommendations
        )

        return plan

    async def _fetch_sipoc_data(self, process_id: str) -> Dict[str, Any]:
        """Fetch SIPOC components from Supabase"""
        if not self.supabase:
            return {}

        # Fetch process details
        proc_res = self.supabase.table("sipoc_processes").select("*").eq("id", process_id).single().execute()
        process = proc_res.data or {}

        # Fetch all components
        comp_res = self.supabase.table("sipoc_components").select("*").eq("process_id", process_id).execute()
        components = comp_res.data or []

        # Fetch relationships (edges)
        edge_res = self.supabase.table("sipoc_edges").select("*").eq("process_id", process_id).execute()
        edges = edge_res.data or []

        return {
            "process": process,
            "components": components,
            "edges": edges
        }

    async def _score_activities_with_claude(
        self,
        sipoc_data: Dict[str, Any],
        company_context: Dict[str, Any]
    ) -> List[AutomationScore]:
        """
        Use Claude to analyze each activity and score automation potential
        """

        # Build prompt with SIPOC components
        components_str = json.dumps(sipoc_data.get("components", []), indent=2, default=str)

        prompt = f"""
You are an expert in process automation analysis. Analyze the following SIPOC process and score each activity for automation potential.

COMPANY CONTEXT:
- Company: {company_context.get('company', 'Unknown')}
- Sector: {company_context.get('sector', 'Unknown')}
- Process: {company_context.get('process', 'Unknown')}

SIPOC COMPONENTS:
{components_str}

For EACH activity/component with type="activity", provide:

1. **Activity Name**: Extracted from content.name
2. **Frequency**: daily, weekly, monthly, quarterly, ad-hoc
3. **Time Spent (minutes)**: Estimated time to complete manually
4. **Manual Effort %**: 0-100, how much is done manually vs automated currently
5. **Business Value**: high, medium, low - impact if automated
6. **Complexity**: simple, moderate, complex - difficulty of automation
7. **Automation Score**: (Frequency × TimeSpent × BusinessValue) / Complexity → 0-100 score
8. **Recommendation**: "automate" (score >= 70), "semi-automate" (50-69), or "keep_manual" (< 50)

Return a JSON array with these fields for each activity.

Scoring Examples:
- Daily task, 45 min, high value, simple = 90+ (automate)
- Weekly task, 20 min, medium value, moderate = 55-65 (semi-automate)
- Ad-hoc task, variable, low value = < 40 (keep manual)

Be specific to {company_context.get('process', 'the process')} in the {company_context.get('sector', 'sector')} domain.
"""

        # Call Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        # Parse response
        response_text = response.content[0].text

        # Extract JSON from response
        try:
            import re
            json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
            if json_match:
                scores_data = json.loads(json_match.group())
            else:
                scores_data = json.loads(response_text)
        except json.JSONDecodeError:
            scores_data = []

        # Convert to AutomationScore objects
        scores = []
        for item in scores_data:
            scores.append(AutomationScore(
                activity=item.get("activity_name", "Unknown"),
                frequency=item.get("frequency", "ad-hoc"),
                time_spent_minutes=item.get("time_spent_minutes", 30),
                manual_effort_pct=item.get("manual_effort_pct", 100),
                business_value=item.get("business_value", "medium"),
                complexity=item.get("complexity", "moderate"),
                automation_score=item.get("automation_score", 0),
                recommendation=item.get("recommendation", "keep_manual")
            ))

        return scores

    def _generate_agent_proposals(
        self,
        activity_scores: List[AutomationScore],
        sipoc_data: Dict[str, Any]
    ) -> List[AgentProposal]:
        """
        Group automatable activities into agent proposals
        """
        proposals = []

        # Filter activities with automation score >= 70
        automatable = [s for s in activity_scores if s.automation_score >= 70]

        # Group by logical role
        activity_groups = self._group_activities_by_role(automatable)

        for i, (role, activities) in enumerate(activity_groups.items(), 1):
            # Determine input and output types from SIPOC components
            activity_names = [a.activity for a in activities]
            input_types = self._infer_input_types(sipoc_data, activity_names)
            output_types = self._infer_output_types(sipoc_data, activity_names)

            # Estimate token budget and turns based on complexity
            total_complexity = sum([1 for a in activities if a.complexity == "complex"])
            token_budget = 10000 + (total_complexity * 5000)
            max_turns = 3 if total_complexity == 0 else (5 if total_complexity < 3 else 7)

            # Estimate execution time
            estimated_time = sum([a.time_spent_minutes for a in activities]) // 60  # in minutes

            proposal = AgentProposal(
                name=f"Agent {i}: {role} Automation",
                role=role,
                activities=activity_names,
                input_types=input_types,
                output_types=output_types,
                suggested_model="claude_code" if total_complexity > 0 else "webhook",
                token_budget=token_budget,
                max_turns=max_turns,
                estimated_time_minutes=estimated_time
            )
            proposals.append(proposal)

        return proposals

    def _group_activities_by_role(self, activities: List[AutomationScore]) -> Dict[str, List[AutomationScore]]:
        """Group activities into logical agent roles"""
        # Simple grouping by activity prefix or domain
        # In a real system, Claude would do this

        groups = {}
        for activity in activities:
            name = activity.activity.lower()

            # Determine group
            if "import" in name or "fetch" in name or "pull" in name:
                role = "Data Importer"
            elif "clean" in name or "normalize" in name or "validate" in name:
                role = "Data Normalizer"
            elif "match" in name or "reconcil" in name or "compare" in name:
                role = "Matcher/Reconciler"
            elif "analyz" in name or "detect" in name or "find" in name:
                role = "Exception Analyzer"
            elif "report" in name or "alert" in name or "notify" in name:
                role = "Reporting/Notification"
            else:
                role = "General Processor"

            if role not in groups:
                groups[role] = []
            groups[role].append(activity)

        return groups

    def _infer_input_types(self, sipoc_data: Dict[str, Any], activity_names: List[str]) -> List[str]:
        """Infer input types from SIPOC components"""
        # Look for "input" type components in SIPOC
        inputs = []
        for comp in sipoc_data.get("components", []):
            if comp.get("type") == "input":
                inputs.append(comp.get("content", {}).get("name", "Unknown"))
        return inputs or ["CSV", "JSON", "Database"]

    def _infer_output_types(self, sipoc_data: Dict[str, Any], activity_names: List[str]) -> List[str]:
        """Infer output types from SIPOC components"""
        # Look for "output" type components in SIPOC
        outputs = []
        for comp in sipoc_data.get("components", []):
            if comp.get("type") == "output":
                outputs.append(comp.get("content", {}).get("name", "Unknown"))
        return outputs or ["Report", "Alert", "Database"]

    def _generate_routine_proposals(
        self,
        agent_proposals: List[AgentProposal],
        sipoc_data: Dict[str, Any]
    ) -> List[RoutineProposal]:
        """
        Generate routine (scheduling) proposals for agents.
        Chains agents together based on dependencies.
        """
        routines = []

        # Create a master routine that chains all agents
        if agent_proposals:
            agents_in_sequence = [agent.name for agent in agent_proposals]

            routine = RoutineProposal(
                name="Master Automation Routine",
                trigger="schedule",
                schedule_cron="0 8 * * 1-5",  # 8 AM weekdays (example)
                event_trigger=None,
                agents=agents_in_sequence,
                success_hooks=[
                    {
                        "type": "send_notification",
                        "recipients": ["controller@company.com"],
                        "message": "Process automation completed successfully"
                    }
                ],
                failure_hooks=[
                    {
                        "type": "send_alert",
                        "recipients": ["ops@company.com"],
                        "priority": "high"
                    },
                    {
                        "type": "retry",
                        "max_attempts": 3,
                        "backoff_seconds": 300
                    }
                ],
                timeout_minutes=120
            )
            routines.append(routine)

        # Create individual routines for high-frequency agents
        for agent in agent_proposals:
            if any("Import" in agent.role or "Fetch" in agent.role for _ in [1]):
                routine = RoutineProposal(
                    name=f"Daily {agent.role} Routine",
                    trigger="schedule",
                    schedule_cron="0 8 * * 1-5",
                    event_trigger=None,
                    agents=[agent.name],
                    success_hooks=[],
                    failure_hooks=[],
                    timeout_minutes=agent.estimated_time_minutes + 10
                )
                routines.append(routine)

        return routines

    def _calculate_roi(
        self,
        activity_scores: List[AutomationScore],
        agent_proposals: List[AgentProposal]
    ) -> Dict[str, float]:
        """Calculate ROI metrics"""

        # Calculate weekly time saved (in hours)
        time_saved_minutes = 0
        for score in activity_scores:
            if score.automation_score >= 70:
                # Weekly frequency mapping
                freq_multiplier = {
                    "daily": 5,  # 5 days/week
                    "weekly": 1,
                    "monthly": 0.25,
                    "quarterly": 0.06,
                    "ad-hoc": 0.1
                }.get(score.frequency, 1)

                time_saved_minutes += score.time_spent_minutes * freq_multiplier

        time_saved_weekly = time_saved_minutes / 60  # Convert to hours

        # Cost savings (assuming $50/hour fully loaded cost)
        hourly_rate = 50
        cost_savings_weekly = time_saved_weekly * hourly_rate
        cost_savings_monthly = cost_savings_weekly * 4.33  # Weeks per month

        # Implementation costs (rough estimate)
        implementation_cost = len(agent_proposals) * 15000  # $15k per agent

        # Payback period in weeks
        payback_weeks = implementation_cost / cost_savings_weekly if cost_savings_weekly > 0 else 999

        return {
            "time_saved_weekly": time_saved_weekly,
            "cost_savings_weekly": cost_savings_weekly,
            "cost_savings_monthly": cost_savings_monthly,
            "cost_savings_yearly": cost_savings_monthly * 12,
            "implementation_cost": implementation_cost,
            "payback_weeks": payback_weeks
        }

    def _identify_dependencies(
        self,
        agent_proposals: List[AgentProposal],
        routine_proposals: List[RoutineProposal]
    ) -> List[Dict[str, str]]:
        """Identify dependencies between agents"""
        dependencies = []

        # Infer dependencies based on agent roles
        for i, agent in enumerate(agent_proposals):
            if "Importer" in agent.role and i + 1 < len(agent_proposals):
                next_agent = agent_proposals[i + 1]
                dependencies.append({
                    "from": agent.name,
                    "to": next_agent.name,
                    "condition": "success"
                })

        return dependencies

    def _identify_risks(
        self,
        sipoc_data: Dict[str, Any],
        agent_proposals: List[AgentProposal]
    ) -> List[str]:
        """Identify potential risks in automation"""
        risks = []

        if not agent_proposals:
            risks.append("No activities identified as automatable")

        # Check for manual intervention points
        components = sipoc_data.get("components", [])
        if any(c.get("type") == "customer" for c in components):
            risks.append("Customer-facing process - ensure change management")

        # Check for approval workflows
        if any("approval" in str(c).lower() for c in components):
            risks.append("Approval workflow present - ensure audit trail")

        # Generic risks
        risks.extend([
            "API dependency on external systems (ensure SLAs are met)",
            "Data quality issues could propagate through automation",
            "Change management required for business process changes"
        ])

        return risks

    def _generate_recommendations(
        self,
        sipoc_data: Dict[str, Any],
        activity_scores: List[AutomationScore],
        agent_proposals: List[AgentProposal],
        roi_metrics: Dict[str, float]
    ) -> List[str]:
        """Generate final recommendations"""
        recommendations = []

        # ROI recommendation
        payback = roi_metrics.get("payback_weeks", 999)
        if payback < 12:
            recommendations.append(f"✅ HIGH ROI: Payback in {payback:.1f} weeks. Recommend proceeding with full automation.")
        elif payback < 26:
            recommendations.append(f"⚠️  MEDIUM ROI: Payback in {payback:.1f} weeks. Consider phased approach.")
        else:
            recommendations.append(f"❌ LOW ROI: Payback in {payback:.1f} weeks. Focus on high-value activities first.")

        # Phasing recommendation
        automatable_high = [s for s in activity_scores if s.automation_score >= 80]
        automatable_medium = [s for s in activity_scores if 70 <= s.automation_score < 80]
        if automatable_high:
            recommendations.append(f"Phase 1: Automate {len(automatable_high)} high-confidence activities ({[s.activity for s in automatable_high][:2]}...)")
        if automatable_medium:
            recommendations.append(f"Phase 2: Automate {len(automatable_medium)} medium-confidence activities after Phase 1 validation")

        # Agent recommendations
        if len(agent_proposals) > 3:
            recommendations.append(f"Build {len(agent_proposals)} agents in total. Start with 'Data Importer' (most critical) and 'Matcher'.")

        # Implementation timeline
        weeks = len(agent_proposals) * 1.5  # Estimate 1.5 weeks per agent
        recommendations.append(f"Estimated implementation timeline: {weeks:.0f} weeks ({weeks/4:.1f} months)")

        # Monitoring recommendation
        recommendations.append("Set up monitoring/alerting for automated processes. Start with 80% automation threshold for alerts.")

        return recommendations


# ===================================================================
# Integration with api.py
# ===================================================================

async def analyze_sipoc_for_automation(request, sipoc_id: str, cognee_context: bool = True):
    """
    API endpoint: POST /api/sipoc/{id}/analyze-automation

    Returns:
    {
        "analysis": AutomationPlan (serialized),
        "agents_to_create": List of agent proposals,
        "routines_to_create": List of routine proposals,
        "roi_metrics": Dict with cost/savings/payback
    }
    """
    suggester = SipocAutomationSuggester(supabase_client=supabase)

    company_context = {
        "company": "CFN",
        "sector": "financeiro",
        "process": "conciliacao"
    }

    plan = await suggester.analyze_sipoc_for_automation(
        sipoc_process_id=sipoc_id,
        company_context=company_context,
        include_cognee_analysis=cognee_context
    )

    return {
        "analysis": {
            "total_automation_potential": plan.total_automation_potential,
            "activities_analyzed": plan.activities_analyzed,
            "activities_automatable": plan.activities_automatable,
            "estimated_weekly_time_saved_hours": plan.estimated_time_saved_hours_per_week,
            "estimated_monthly_cost_savings": plan.estimated_cost_savings_usd_per_month,
            "payback_period_weeks": plan.payback_period_weeks
        },
        "agents_proposed": [
            {
                "name": a.name,
                "role": a.role,
                "activities": a.activities,
                "suggested_model": a.suggested_model,
                "token_budget": a.token_budget,
                "max_turns": a.max_turns
            }
            for a in plan.proposed_agents
        ],
        "routines_proposed": [
            {
                "name": r.name,
                "trigger": r.trigger,
                "schedule": r.schedule_cron if r.trigger == "schedule" else r.event_trigger,
                "agents": r.agents,
                "timeout_minutes": r.timeout_minutes
            }
            for r in plan.proposed_routines
        ],
        "risks": plan.risks,
        "recommendations": plan.recommendations,
        "next_steps": [
            "1. Review automation plan with business stakeholders",
            "2. Approve agent and routine proposals",
            "3. Begin implementation with Phase 1 agents",
            "4. Set up monitoring and alerting"
        ]
    }
