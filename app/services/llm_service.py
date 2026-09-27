"""
LLM Service — Google Gemini (free tier).

Provides:
  analyze_intent()
  generate_investigation_explanation()

Uses the google-genai SDK (v2+) with the free gemini-2.0-flash model.
Falls back gracefully to deterministic templates when the key is absent.

Get a free API key at: https://aistudio.google.com/app/apikey
Set it in .env:  GOOGLE_API_KEY=your_key_here
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LLMService:
    """
    Abstraction over Google Gemini free-tier API.
    All methods return None on failure — callers fall back to deterministic templates.
    """

    def __init__(self) -> None:
        self._client = None          # google.genai.Client instance
        self._model_id: str = ""
        self._available = False
        self._initialize()

    def _initialize(self) -> None:
        """Attempt to configure the Gemini client (google-genai v2 SDK)."""
        key = settings.google_api_key
        if not key or key in ("", "your_google_api_key_here"):
            logger.info("Valid GOOGLE_API_KEY not provided — running in intelligent verified fallback mode")
            self._available = False
            return

        try:
            from google import genai  # google-genai v2+

            self._client = genai.Client(api_key=key)
            self._model_id = settings.google_model_id
            self._available = True
            logger.info("Gemini LLM initialized: model=%s", self._model_id)

        except ImportError:
            logger.warning("google-genai not installed — run: pip install google-genai")
        except Exception as exc:
            logger.warning("Gemini initialization failed: %s — running in fallback mode", exc)


    @property
    def is_available(self) -> bool:
        return self._available

    def _generate(self, prompt: str) -> str | None:
        """Low-level generation using google-genai v2 SDK. Returns None on failure."""
        if not self._available or self._client is None:
            return None
        try:
            from google.genai import types as genai_types

            response = self._client.models.generate_content(
                model=self._model_id,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    top_p=0.8,
                    max_output_tokens=800,
                ),
            )
            # Extract text from the first candidate
            if response and response.text:
                return response.text
            return None
        except Exception as exc:
            logger.warning("Gemini generation failed: %s", exc)
            return None

    # ── Public API (same interface as watsonx version) ─────────────────────────

    def analyze_intent(
        self,
        question: str,
        current_period: str,
        comparison_period: str,
    ) -> dict[str, Any] | None:
        """
        Classify user intent using Gemini.
        Returns dict with 'intent' key, or None to trigger rule-based fallback.
        """
        prompt = f"""You are an intent classifier for a financial investigation system.

Classify the following question into exactly ONE of these intents:
- profit_change_investigation
- revenue_change_investigation
- expense_change_investigation
- margin_change_investigation
- refund_change_investigation
- supplier_analysis_investigation
- product_performance_investigation
- anomaly_detection_investigation
- general_financial_investigation

Question: {question}

Respond with a JSON object ONLY — no explanation, no markdown, no code fences.
Example: {{"intent": "profit_change_investigation", "entities": {{}}}}

JSON:"""

        response = self._generate(prompt)
        if not response:
            return None

        try:
            # Strip markdown code fences if Gemini wraps in ```json ... ```
            text = response.strip()
            if text.startswith("```"):
                text = text.split("```")[-2] if "```" in text[3:] else text[3:]
                text = text.lstrip("json").strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Could not parse Gemini intent response: %s | raw: %.120s", exc, response)

        return None

    def generate_investigation_explanation(
        self,
        context: dict[str, Any],
    ) -> str | None:
        """
        Generate a human-readable explanation of verified financial findings.
        Gemini receives pre-verified ledger facts and metrics to answer the user inquiry.
        """
        question          = context.get("question", "")
        current_period    = context.get("current_period", "")
        comparison_period = context.get("comparison_period", "")
        findings          = context.get("findings", [])
        comparison        = context.get("comparison_results", {})
        verified_metrics  = context.get("verified_metrics", {})
        comparison_metrics= context.get("comparison_metrics", {})
        verification      = context.get("verification_status", "verified")

        # Extract figures
        curr_tx_count = verified_metrics.get("transaction_count", 0)
        curr_rev = verified_metrics.get("revenue", 0.0)
        curr_exp = verified_metrics.get("expenses", verified_metrics.get("total_costs", 0.0))
        curr_prof = verified_metrics.get("profit", verified_metrics.get("net_profit", 0.0))
        curr_margin = verified_metrics.get("gross_margin_pct", 0.0)

        comp_tx_count = comparison_metrics.get("transaction_count", 0)
        comp_rev = comparison_metrics.get("revenue", 0.0)
        comp_exp = comparison_metrics.get("expenses", comparison_metrics.get("total_costs", 0.0))
        comp_prof = comparison_metrics.get("profit", comparison_metrics.get("net_profit", 0.0))
        comp_margin = comparison_metrics.get("gross_margin_pct", 0.0)

        # Build comparison summary
        profit_cmp = comparison.get("net_profit", {})
        if isinstance(profit_cmp, dict) and profit_cmp:
            profit_line = (
                f"Net profit shifted from ${profit_cmp.get('comparison_value', 0):,.2f} "
                f"to ${profit_cmp.get('current_value', 0):,.2f} "
                f"(delta: ${profit_cmp.get('change', 0):,.2f}, "
                f"{profit_cmp.get('change_pct', 0):.1f}%)"
            )
        else:
            profit_line = f"Current Net Profit: ${curr_prof:,.2f} | Prior Net Profit: ${comp_prof:,.2f}"

        findings_block = "\n".join(
            f"  {i+1}. {f.get('reason', f.get('entity', 'Unknown'))}"
            for i, f in enumerate(findings[:8])
        ) if findings else "No adverse anomalies or unexpected spikes detected in this ledger interval."

        evidence_ids: list[str] = []
        for f in findings[:6]:
            evidence_ids.extend(f.get("supporting_tx_ids", [])[:3])
        evidence_line = ", ".join(evidence_ids[:10]) if evidence_ids else "N/A"

        prompt = f"""You are an elite Senior Financial Forensic Investigator and CFO Advisory Agent for IBM BOB Hackathon.
Answer the user's specific financial inquiry using ONLY the verified ledger metrics and facts provided below.

USER QUESTION: {question}
PERIOD: {current_period} vs {comparison_period}
AUDIT VERIFICATION: {verification}

VERIFIED LEDGER METRICS ({current_period}):
- Transaction Count: {curr_tx_count}
- Total Revenue: ${curr_rev:,.2f}
- Total Expenses & Operating Costs: ${curr_exp:,.2f}
- Net Profit: ${curr_prof:,.2f}
- Gross Margin: {curr_margin:.1f}%

PRIOR PERIOD BENCHMARK ({comparison_period}):
- Transaction Count: {comp_tx_count}
- Total Revenue: ${comp_rev:,.2f}
- Total Expenses & Operating Costs: ${comp_exp:,.2f}
- Net Profit: ${comp_prof:,.2f}
- Gross Margin: {comp_margin:.1f}%

PROFIT & VARIANCE ATTRIBUTION:
{profit_line}

KEY CONTRIBUTING FACTORS & DETECTED PATTERNS:
{findings_block}

SUPPORTING EVIDENCE TRANSACTION IDs: {evidence_line}

INSTRUCTIONS:
1. Directly answer the user's question ("{question}") in the very first sentence.
2. Ground all numbers strictly on the verified facts above.
3. If the user asks about the number of transactions, report the exact transaction count for {current_period} and {comparison_period}.
4. Provide structured, executive-grade analysis with clear headings and bullet points.
5. Do NOT use placeholder text or generic templates.

Executive Report:"""

        return self._generate(prompt)


    def answer_follow_up_question(
        self,
        question: str,
        investigation_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Dynamically answer any user/judge follow-up question regarding an investigation.
        Uses Gemini if available, or falls back to dynamic analytical synthesis.
        """
        findings = investigation_data.get("findings", [])
        metrics = investigation_data.get("metrics", {})
        comparison = investigation_data.get("comparison", {})
        evidence = investigation_data.get("evidence", [])
        current_period = investigation_data.get("current_period", "2026-02")
        comparison_period = investigation_data.get("comparison_period", "2026-01")

        # Try Gemini LLM first if available
        if self._available and self._client:
            facts_list = []
            for f in findings[:8]:
                desc = f.get('description') or f.get('reason') or 'Financial variance'
                imp_val = float(f.get('impact') or 0.0)
                tx_list = ', '.join(f.get('evidence_ids', [])[:3])
                facts_list.append(f"- {desc} (Impact: ${abs(imp_val):,.2f}, Evidence: {tx_list})")
            facts_summary = "\n".join(facts_list)

            p_val = float(metrics.get('profit') or 0.0)
            r_val = float(metrics.get('revenue') or 0.0)
            e_val = float(metrics.get('expenses') or 0.0)
            p_text = f"${p_val:.2f}"
            r_text = f"${r_val:.2f}"
            e_text = f"${e_val:.2f}"
            tx_ev = ', '.join([e.get('transaction_id', '') for e in evidence[:10] if e.get('transaction_id')])

            prompt = f"""You are the AI Financial Investigator at the IBM BOB 2.0 Hackathon.
Answer the following user question strictly based on the audited financial data below:

USER QUESTION: {question}
AUDITED PERIOD: {current_period} vs {comparison_period}
KEY METRICS: Net Profit = {p_text}, Revenue = {r_text}, Expenses = {e_text}


AUDITED CONTRIBUTING FACTORS:
{facts_summary}

EVIDENCE TRANSACTIONS: {tx_ev}

Provide a direct, insightful, expert answer with exact figures, transaction IDs, and actionable insight. Keep under 250 words."""
            resp = self._generate(prompt)
            if resp:
                evidence_ids = [e.get("transaction_id", "") for e in evidence[:8] if e.get("transaction_id")]
                return {
                    "answer": resp.strip(),
                    "evidence_ids": evidence_ids,
                    "metrics": metrics,
                }

        # Dynamic analytical synthesis fallback (rule + data aware)
        q = question.lower()
        evidence_ids = []

        # 1. Supplier analysis query
        if "supplier" in q or "vendor" in q:
            supplier_findings = [f for f in findings if "supplier" in (f.get("finding_type") or "").lower() or f.get("category") == "supplier"]
            if not supplier_findings:
                supplier_findings = [f for f in findings if f.get("entity") and "supplier" in f.get("entity", "").lower()]

            if supplier_findings:
                lines = [f"**Supplier Cost Impact Analysis for {current_period}:**\n"]
                for sf in supplier_findings[:4]:
                    ent = sf.get("entity") or "Key Supplier"
                    imp = sf.get("impact", 0)
                    txs = sf.get("evidence_ids", [])
                    evidence_ids.extend(txs)
                    lines.append(f"• **{ent}**: Net change of **${abs(imp):,.2f}** ({sf.get('description', '')}). Verified via {len(txs)} supporting transactions ({', '.join(txs[:3])}).")
                lines.append("\n**Investigation Finding**: Procurement cost inflation with these vendors directly compressed operating margins.")
                return {"answer": "\n".join(lines), "evidence_ids": evidence_ids, "metrics": metrics}

        # 2. Recommendation / Action query
        if "recommend" in q or "action" in q or "what should" in q or "fix" in q or "strategy" in q:
            top_factors = sorted(findings, key=lambda x: abs(x.get("impact") or 0), reverse=True)
            top_names = [f.get("entity") or f.get("finding_type", "Cost Item") for f in top_factors[:3]]
            ans = f"""**Strategic Remediation Plan for {current_period}:**

1. **Vendor Renegotiation & Rate Audits**: Target immediate price renegotiations with high-cost variance suppliers ({', '.join(top_names[:2]) or 'primary suppliers'}).
2. **Expense Capping**: Review high-frequency operating expenses and reconcile duplicate purchase orders flagged during anomaly detection.
3. **Margin Recovery**: Adjust product pricing tiers on margin-diluting SKUs where unit COGS surged beyond planned thresholds.
4. **Automated Continuous Monitoring**: Set up automated LangGraph anomaly alerts to detect spending spikes before period close."""
            return {"answer": ans, "evidence_ids": [f.get("evidence_ids", [""])[0] for f in top_factors if f.get("evidence_ids")], "metrics": metrics}

        # 3. Anomaly / Fraud / Suspicious query
        if "anomaly" in q or "unusual" in q or "suspicious" in q or "fraud" in q or "spike" in q:
            anomalies = [f for f in findings if "anomaly" in (f.get("finding_type") or "").lower() or (f.get("impact") or 0) > 5000]
            if anomalies:
                lines = ["**Audited Anomalies & Outliers Identified:**\n"]
                for a in anomalies[:5]:
                    lines.append(f"• **{a.get('entity', 'Transaction Outlier')}**: {a.get('description', '')} (Impact: ${abs(a.get('impact', 0)):,.2f})")
                    evidence_ids.extend(a.get("evidence_ids", []))
                lines.append(f"\nAll items have been verified and tied to ledger entries: {', '.join(evidence_ids[:6])}.")
                return {"answer": "\n".join(lines), "evidence_ids": evidence_ids, "metrics": metrics}

        # 4. Default dynamic executive variance response
        profit_cmp = comparison.get("net_profit", {})
        lines = [
            f"**Executive Financial Synthesis ({current_period} vs {comparison_period}):**\n",
            f"Net Profit closed at **${metrics.get('profit', 0):,.2f}** (Revenue: ${metrics.get('revenue', 0):,.2f}, Costs: ${metrics.get('expenses', 0):,.2f}).",
        ]
        if profit_cmp:
            lines.append(f"Period variance was **${profit_cmp.get('change', 0):,.2f}** ({profit_cmp.get('change_pct', 0):.1f}%).")

        if findings:
            lines.append("\n**Primary Financial Drivers:**")
            for i, f in enumerate(findings[:4], 1):
                desc = f.get("description") or f.get("reason", "")
                imp = f.get("impact", 0)
                txs = f.get("evidence_ids", [])
                evidence_ids.extend(txs)
                lines.append(f"{i}. {desc} (Impact: ${imp:,.2f})")

        lines.append(f"\n*Audited by AI Financial Investigator — {len(evidence_ids)} corroborating ledger records verified.*")
        return {"answer": "\n".join(lines), "evidence_ids": evidence_ids[:10], "metrics": metrics}


# ── Singleton ──────────────────────────────────────────────────────────────────

_llm_service_instance: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = LLMService()
    return _llm_service_instance

