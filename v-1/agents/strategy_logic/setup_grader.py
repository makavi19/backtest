# agents/strategy_logic/setup_grader.py
# Detailed ICT setup grading and scoring

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum, auto
import pandas as pd


class Grade(Enum):
    A_PLUS = auto()
    A = auto()
    B_PLUS = auto()
    B = auto()
    C = auto()
    D = auto()
    
    def __lt__(self, other):
        return self.value < other.value


@dataclass
class GradingResult:
    final_grade: Grade
    numeric_score: float  # 0.0 to 1.0
    breakdown: Dict[str, float]
    strengths: List[str]
    weaknesses: List[str]
    recommendation: str  # 'immediate', 'selective', 'reject'


class SetupGrader:
    """
    Granular grading system for ICT setups
    
    Breaks down into components, weights by importance
    """
    
    # Component weights (must sum to 1.0)
    WEIGHTS = {
        'order_block': 0.25,
        'fair_value_gap': 0.20,
        'market_structure': 0.20,
        'htf_alignment': 0.20,
        'risk_reward': 0.15,
    }
    
    def grade_setup(
        self,
        has_ob: bool,
        ob_quality: float,  # 0-1
        ob_freshness: float,  # 0-1
        
        has_fvg: bool,
        fvg_freshness: float,  # 0-1
        fvg_filled: bool,
        
        mss_confirmed: bool,  # Market structure shift
        htf_bullish: bool,
        htf_bearish: bool,
        
        risk_reward: float,  # 1.5, 2.0, 3.0, etc.
        direction: str
    ) -> GradingResult:
        """
        Complete setup grading
        """
        breakdown = {}
        strengths = []
        weaknesses = []
        
        # 1. Order Block scoring
        if has_ob:
            ob_score = 0.5 * ob_quality + 0.5 * ob_freshness
            breakdown['order_block'] = ob_score
            
            if ob_freshness > 0.8:
                strengths.append('Fresh, untested Order Block')
            elif ob_freshness < 0.5:
                weaknesses.append('Order Block partially tested')
        else:
            ob_score = 0.0
            breakdown['order_block'] = 0.0
            weaknesses.append('No Order Block present')
        
        # 2. FVG scoring
        if has_fvg:
            fvg_score = fvg_freshness if not fvg_filled else fvg_freshness * 0.5
            breakdown['fair_value_gap'] = fvg_score
            
            if not fvg_filled:
                strengths.append('Unfilled Fair Value Gap')
            else:
                weaknesses.append('FVG partially filled')
        else:
            fvg_score = 0.0
            breakdown['fair_value_gap'] = 0.0
        
        # 3. Market Structure
        if mss_confirmed:
            structure_score = 1.0
            breakdown['market_structure'] = 1.0
            strengths.append('Market Structure Shift confirmed')
        else:
            structure_score = 0.3  # Weak structure
            breakdown['market_structure'] = 0.3
            weaknesses.append('Market Structure unclear')
        
        # 4. HTF Alignment
        if direction == 'buy' and htf_bullish:
            htf_score = 1.0
            strengths.append('Higher timeframe bullish')
        elif direction == 'sell' and htf_bearish:
            htf_score = 1.0
            strengths.append('Higher timeframe bearish')
        elif (htf_bullish or htf_bearish):  # HTF has direction but mismatch
            htf_score = 0.5
            weaknesses.append('HTF direction conflicts with setup')
        else:
            htf_score = 0.3
            weaknesses.append('Higher timeframe unclear')
        
        breakdown['htf_alignment'] = htf_score
        
        # 5. Risk:Reward
        if risk_reward >= 3.0:
            rr_score = 1.0
        elif risk_reward >= 2.0:
            rr_score = 0.9
        elif risk_reward >= 1.5:
            rr_score = 0.7
        else:
            rr_score = max(0, risk_reward / 2.0)
            weaknesses.append(f'R:R only {risk_reward:.1f}')
        
        breakdown['risk_reward'] = rr_score
        
        # Calculate weighted total
        total = sum(
            breakdown[component] * weight
            for component, weight in self.WEIGHTS.items()
        )
        
        # Determine grade
        final_grade = self._score_to_grade(total)
        
        # Recommendation
        recommendation = self._get_recommendation(final_grade, len(weaknesses))
        
        return GradingResult(
            final_grade=final_grade,
            numeric_score=round(total, 3),
            breakdown=breakdown,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendation=recommendation
        )
    
    def _score_to_grade(self, score: float) -> Grade:
        """Convert 0-1 score to letter grade"""
        if score >= 0.90:
            return Grade.A_PLUS
        elif score >= 0.80:
            return Grade.A
        elif score >= 0.70:
            return Grade.B_PLUS
        elif score >= 0.60:
            return Grade.B
        elif score >= 0.45:
            return Grade.C
        else:
            return Grade.D
    
    def _get_recommendation(self, grade: Grade, num_weaknesses: int) -> str:
        """Trading recommendation based on grade"""
        if grade <= Grade.B and num_weaknesses <= 1:
            return 'immediate'
        elif grade <= Grade.B_PLUS and num_weaknesses <= 2:
            return 'selective'
        elif grade == Grade.C:
            return 'discard'
        else:
            return 'reject'
    
    def quick_grade(self, scan_result) -> str:
        """Fast grade from scanner result"""
        # Map scanner grade to full grade
        grade_map = {
            'A': Grade.A,
            'B': Grade.B,
            'C': Grade.C,
        }
        return grade_map.get(scan_result.grade, Grade.D)