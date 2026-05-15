"""
TOKEN ECONOMY SIMULATOR — cadCAD AGENT-BASED MODEL
====================================================
Specification and skeleton code for developer use.

Version: 1.0
Framework: cadCAD 0.5.3
Reference papers:
  - Domenicale et al. (2025) "A Diagnostic Framework for
    Identifying Design-Stage Failure Modes in Tokenized
    Collaborative Economies" (Paper 1)
  - Domenicale et al. (2026) "A Tool for Designing Tokenized
    Collaborative Economies" (Paper 2, GoodIT 2026)

========================================================
SECTION 0: CADCAD MODEL ARCHITECTURE
========================================================

In cadCAD a model is a state machine. At each tick:

  1. POLICY FUNCTIONS
     Each agent observes the current state and produces
     a signal (its decision). Policy functions are PURE —
     they do not modify state, only return signals.

  2. STATE UPDATE FUNCTIONS
     Signals from policy functions are aggregated and
     the system state is updated. These functions modify
     state variables.

  3. RECORD
     The new state is recorded in the output dataframe.

The four building blocks are:
  - state_variables: what the system holds in memory
  - initial_conditions: values at tick 0
  - policy_functions: agent decisions
  - state_update_functions: how decisions change state

========================================================
SECTION 1: THEORETICAL BACKGROUND
========================================================

AGENT TYPES (from Domenicale et al. 2025 DLT paper):

  Initiator      — community manager, launches the system,
                   assigns roles, adjusts parameters.
                   Motivation: governance-oriented.

  Association    — non-profit organizations, organize
                   initiatives, issue Purpose Driven Tokens
                   and Badges, verify contributions.
                   Motivation: mission/social-oriented.

  Local Retailer — small businesses, issue Coupons,
                   receive tokens through redemptions.
                   Motivation: economic-oriented.

  Community Member — citizens, participate in activities,
                   earn tokens, redeem coupons, accumulate
                   badges, may obtain SBT membership.
                   Motivation: mixed intrinsic/extrinsic.

TOKEN TYPES (from Domenicale et al. 2025 DLT paper):

  Community Value Token (ERC20)  — medium of exchange,
                                   freely transferable
  Purpose Driven Token (ERC20)   — output-based reward,
                                   role-based minting,
                                   restricted transfer
  Coupon (ERC20)                 — access to goods/services,
                                   burnable upon redemption
  Badge (ERC721)                 — proof of participation,
                                   non-transferable after
                                   receipt, optionally
                                   burnable for rewards
  Membership SBT (ERC721)        — governance right,
                                   non-transferable,
                                   contribution-based
  Physical Object NFT (ERC721)   — borrowing access,
                                   temporary transfer

UTILITY FUNCTIONS:

  All agents have utility:
    U = alpha * U_econ + beta * U_social + gamma * U_govern

  Where:
    U_econ   = economic utility (token balance, redemptions)
    U_social = social utility (participation, reputation,
               belonging — captures intrinsic motivation
               per Self-Determination Theory)
    U_govern = governance utility (SBT, voting influence)

  Motivational weights alpha/beta/gamma vary by agent type
  and capture heterogeneity in the crowding-out effect
  (Bénabou & Tirole 2003): monetary rewards can undermine
  intrinsic motivation if alpha dominates.

DECISION RULE:
  All binary decisions use a logistic function:
    P(action) = sigma(net_utility - threshold)
    sigma(x)  = 1 / (1 + exp(-x))

========================================================
SECTION 2: IMPORTS AND CONFIGURATION
========================================================
"""

import numpy as np
import pandas as pd
from cadCAD.configuration import Experiment
from cadCAD.configuration.utils import config_sim
from cadCAD.engine import ExecutionMode, ExecutionContext, Executor
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any
import random

# ── Reproducibility ───────────────────────────────────
SEED = 42
np.random.seed(SEED)
random.seed(SEED)

# ── Simulation parameters ─────────────────────────────
N_WEEKS        = 52       # simulation horizon (ticks)
N_RUNS         = 10       # Monte Carlo runs
N_MEMBERS      = 100      # initial Community Members
N_ASSOCIATIONS = 4        # initial Associations
N_RETAILERS    = 8        # initial Local Retailers
N_INITIATORS   = 1        # always 1

"""
========================================================
SECTION 3: AGENT DATA STRUCTURES
========================================================
Each agent is a dataclass holding its state variables.
These are stored in the system state as lists of dicts
for cadCAD compatibility.
"""

@dataclass
class CommunityMember:
    """
    State variables for a Community Member agent.

    Motivational weights (alpha + beta + gamma = 1):
      alpha — extrinsic/economic weight
      beta  — intrinsic/social weight
      gamma — governance weight

    Per Self-Determination Theory (Ryan & Deci 2020),
    community members in collaborative economies tend
    toward high beta (intrinsic motivation dominant).
    """
    id: int
    # Motivational weights — sampled at initialisation
    alpha: float = 0.0   # extrinsic weight U[0.1, 0.5]
    beta:  float = 0.0   # intrinsic weight U[0.4, 0.8]
    gamma: float = 0.0   # governance weight U[0.0, 0.3]
    # Activation threshold — cost of participation
    theta: float = 0.0   # U[0.1, 0.6]
    # Token balances
    balance_cvt:   int = 0    # Community Value Tokens
    balance_pdt:   int = 0    # Purpose Driven Tokens
    coupons:       int = 0    # Coupons held
    badges:        int = 0    # Badges accumulated
    has_sbt:       bool = False  # Membership SBT
    # Participation history
    weeks_active:      int = 0
    total_redemptions: int = 0
    # Status
    is_active: bool = True

    def utility(self, avg_coupon_value: float = 1.0) -> float:
        """
        Compute current utility.
        U = alpha * U_econ + beta * U_social + gamma * U_govern

        U_econ   = token balance + coupon value
        U_social = participation level + reputation (badges)
        U_govern = 1 if SBT held, 0 otherwise
        """
        u_econ   = (self.balance_cvt + self.balance_pdt
                    + self.coupons * avg_coupon_value)
        u_social = (0.5 * self.weeks_active
                    + 0.5 * self.badges)
        u_govern = float(self.has_sbt)
        return (self.alpha * u_econ
                + self.beta  * u_social
                + self.gamma * u_govern)

    def p_participate(self,
                      expected_token_gain: float) -> float:
        """
        Probability of participating in an activity this tick.

        P(participate) = sigma(beta * u_social
                               + alpha * expected_gain
                               - theta)

        High beta → social satisfaction drives participation
        High theta → higher cost/barrier to participate
        """
        net = (self.beta  * (0.5 * self.weeks_active
                             + 0.5 * self.badges)
               + self.alpha * expected_token_gain
               - self.theta)
        return _sigmoid(net)

    def p_spend(self,
                best_coupon_value: float,
                holding_incentive: float = 0.0) -> float:
        """
        Probability of redeeming tokens for a coupon.

        P(spend) = sigma(alpha * coupon_value
                         - beta * holding_incentive)

        holding_incentive > 0 if staking/tiered redemption
        exists — reduces probability of immediate spending.
        If no coupons available, returns 0.
        """
        if best_coupon_value <= 0:
            return 0.0
        net = (self.alpha * best_coupon_value
               - self.beta  * holding_incentive)
        return _sigmoid(net)

    def p_burn_badge(self,
                     reward_value: float,
                     min_badges: int = 3) -> float:
        """
        Probability of burning badges for additional rewards.

        P(burn) = sigma(alpha * reward_value
                        - beta * badges_held)

        High beta → agent values reputation, reluctant
        to burn badges even for rewards.
        Only active if badges >= min_badges.
        """
        if self.badges < min_badges:
            return 0.0
        net = (self.alpha * reward_value
               - self.beta  * self.badges)
        return _sigmoid(net)

    def p_exit(self,
               mean_utility: float) -> float:
        """
        Probability of leaving the system this tick.

        P(exit) = sigma(-U_self + delta * max(0, U_mean - U_self))

        If own utility falls significantly below the community
        mean, exit probability increases. delta = 0.3 default
        (sensitivity to social comparison).
        """
        delta = 0.3
        u_self = self.utility()
        gap    = max(0.0, mean_utility - u_self)
        net    = -u_self + delta * gap
        return _sigmoid(net)


@dataclass
class Association:
    """
    State variables for an Association agent.

    Motivation: mission/social-oriented.
    Primary actions: organise initiatives, issue PDTs
    and Badges, verify contributions, issue SBTs.

    alpha_ass — mission weight  U[0.6, 0.9]
    beta_ass  — capacity weight = 1 - alpha_ass
    """
    id: int
    alpha_ass:    float = 0.0   # mission weight
    beta_ass:     float = 0.0   # capacity weight
    org_cost:     float = 0.0   # cost of organising U[0.1, 0.4]
    verif_prob:   float = 0.0   # verification effectiveness
    sbt_threshold: int  = 5     # weeks active needed for SBT
    # State
    initiatives_run: int = 0
    tokens_issued:   int = 0
    badges_issued:   int = 0
    is_active:       bool = True

    def p_organise(self, n_active_members: int) -> float:
        """
        Probability of organising an initiative this tick.

        P(organise) = sigma(alpha_ass * n_active_members
                            - org_cost)

        More active members → higher incentive to organise.
        """
        net = self.alpha_ass * (n_active_members / 10.0) - self.org_cost
        return _sigmoid(net)

    def verify_contribution(self) -> bool:
        """
        Whether a contribution is verified this tick.
        Stochastic: P(verify) = verif_prob

        verif_prob values by mechanism (from diagnostic layer):
          Physical presence:     0.95
          Smart contract:        0.90
          Peer verification:     0.80
          Third-party cert:      0.75
          Self-reporting:        0.10
        """
        return random.random() < self.verif_prob


@dataclass
class LocalRetailer:
    """
    State variables for a Local Retailer agent.

    Motivation: economic-oriented.
    Primary actions: issue coupons, renew coupons,
    receive tokens through redemptions.

    alpha_lr — economic weight U[0.5, 0.8]
    beta_lr  — reputational weight = 1 - alpha_lr
    """
    id: int
    alpha_lr:      float = 0.0
    beta_lr:       float = 0.0
    renewal_cost:  float = 0.0   # perceived cost of renewal
    coupon_value:  int   = 10    # tokens required per coupon
    max_coupons:   int   = 5     # max coupons per period
    # State
    coupons_active:    int = 0
    total_redemptions: int = 0
    tokens_received:   int = 0
    weeks_since_renew: int = 0
    is_active:         bool = True

    def p_issue_coupon(self,
                       expected_redemptions: float) -> float:
        """
        Probability of issuing coupons this tick.

        P(issue) = sigma(alpha_lr * expected_redemptions
                         - renewal_cost)

        Low expected_redemptions → retailer may not bother.
        This captures the provider free-rider risk identified
        in Failure Mode 4 of the diagnostic framework.
        """
        net = (self.alpha_lr * expected_redemptions
               - self.renewal_cost)
        return _sigmoid(net)

    def n_coupons_to_issue(self,
                           tokens_received_last: int) -> int:
        """
        Number of coupons to issue, based on last period
        token inflow. Capped at max_coupons.

        n = round(alpha_lr * tokens_received_last
                  / coupon_value)
        """
        if tokens_received_last <= 0:
            return 0
        n = round(self.alpha_lr
                  * tokens_received_last
                  / self.coupon_value)
        return min(n, self.max_coupons)

    def p_renew(self,
                redemptions_last_2_weeks: int) -> float:
        """
        Probability of renewing coupons at the 2-week cycle.

        P(renew) = sigma(alpha_lr * redemptions
                         - beta_lr * renewal_cost)

        Low redemptions → retailer does not renew →
        absorptive capacity Q drops → FM1 oversupply risk
        increases.
        """
        net = (self.alpha_lr * redemptions_last_2_weeks
               - self.beta_lr * self.renewal_cost)
        return _sigmoid(net)


@dataclass
class Initiator:
    """
    State variables for the Initiator agent.

    The Initiator does not participate in token economy
    directly. It monitors system health and adjusts
    parameters to maintain sustainability.

    Utility is over system-level outcomes:
      U_init = w1 * N_active
             + w2 * (1 - exit_rate)
             + w3 * I(rho >= 1)
             + w4 * (1 - Gamma)
    """
    id: int = 0
    intervention_threshold_exit:   float = 0.10
    intervention_threshold_supply: float = 0.5
    emission_adjustment_factor:    float = 0.10
    # State
    interventions_made: int = 0

    def should_adjust_emission(self,
                                rho: float,
                                consecutive_weeks: int) -> bool:
        """
        Trigger emission reduction if burn coverage ratio
        rho < threshold for 2+ consecutive weeks.
        """
        return (rho < self.intervention_threshold_supply
                and consecutive_weeks >= 2)

    def should_intervene_engagement(self,
                                     exit_rate: float) -> bool:
        """
        Trigger engagement intervention if weekly exit rate
        exceeds threshold.
        """
        return exit_rate > self.intervention_threshold_exit


"""
========================================================
SECTION 4: HELPER FUNCTIONS
========================================================
"""

def _sigmoid(x: float) -> float:
    """Logistic function mapping real values to (0, 1)."""
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))


def initialise_agents(n_members:      int = N_MEMBERS,
                      n_associations: int = N_ASSOCIATIONS,
                      n_retailers:    int = N_RETAILERS
                      ) -> Tuple[List, List, List, Any]:
    """
    Create and initialise all agents with heterogeneous
    motivational parameters sampled from distributions
    defined in the diagnostic framework specification.

    Returns: (members, associations, retailers, initiator)
    """
    members = []
    for i in range(n_members):
        # Sample motivational weights with constraint
        # alpha + beta + gamma = 1
        alpha = np.random.uniform(0.1, 0.5)
        gamma = np.random.uniform(0.0, 0.3)
        beta  = max(0.0, 1.0 - alpha - gamma)
        # Normalise
        total = alpha + beta + gamma
        members.append(CommunityMember(
            id    = i,
            alpha = alpha / total,
            beta  = beta  / total,
            gamma = gamma / total,
            theta = np.random.uniform(0.1, 0.6),
            balance_cvt = np.random.randint(0, 10),
        ))

    associations = []
    for i in range(n_associations):
        alpha_ass = np.random.uniform(0.6, 0.9)
        associations.append(Association(
            id          = i,
            alpha_ass   = alpha_ass,
            beta_ass    = 1.0 - alpha_ass,
            org_cost    = np.random.uniform(0.1, 0.4),
            verif_prob  = 0.80,  # peer verification default
            sbt_threshold = 5,
        ))

    retailers = []
    for i in range(n_retailers):
        alpha_lr = np.random.uniform(0.5, 0.8)
        retailers.append(LocalRetailer(
            id           = i,
            alpha_lr     = alpha_lr,
            beta_lr      = 1.0 - alpha_lr,
            renewal_cost = np.random.uniform(0.1, 0.4),
            coupon_value = np.random.choice([5, 10, 15]),
            max_coupons  = 5,
        ))

    initiator = Initiator(id=0)
    return members, associations, retailers, initiator


"""
========================================================
SECTION 5: STATE VARIABLES AND INITIAL CONDITIONS
========================================================
State variables are the complete memory of the system
at each tick. In cadCAD these are defined as a dict.
"""

def build_initial_state() -> dict:
    """
    Build the initial state dict for cadCAD.

    All agent lists are stored here. System-level
    aggregates are also stored for efficiency —
    avoids recomputing from agent lists every tick.
    """
    members, associations, retailers, initiator = \
        initialise_agents()

    return {
        # ── Agent populations ──────────────────────────
        'members':      members,
        'associations': associations,
        'retailers':    retailers,
        'initiator':    initiator,

        # ── Token supply dynamics ──────────────────────
        # FM1: Oversupply | FM3: Burn/Emission Imbalance
        'M_total':      sum(m.balance_cvt for m in members),
        'E_t':          0,     # tokens emitted this tick
        'B_t':          0,     # tokens burned this tick
        'rho':          0.0,   # burn coverage ratio B/E
        'E_cumulative': 0,     # total ever emitted
        'B_cumulative': 0,     # total ever burned

        # ── Velocity dynamics ──────────────────────────
        # FM2: Velocity Trap
        'tau_bar':      7.0,   # wealth-weighted avg hold (days)
        'V_lower':      1/7,   # velocity lower bound 1/tau_bar
        'V_star':       0.0,   # stable velocity threshold PQ/M

        # ── Exchange market ────────────────────────────
        # FM1 (absorptive capacity) | FM5 (critical mass)
        'Q_t':          0,     # transactions this tick
        'P_avg':        10.0,  # average coupon price (tokens)
        'coupons_available': sum(r.coupons_active
                                 for r in retailers),

        # ── Participation dynamics ─────────────────────
        # FM4: Free-Rider | FM5: Critical Mass
        'N_active':     len(members),
        'phi_t':        0.0,   # active contributor rate
        'exit_rate_t':  0.0,   # fraction exiting this tick
        'N_star':       0,     # critical mass threshold

        # ── Governance ─────────────────────────────────
        # FM6: Governance Capture
        'Gamma':        1.0,   # centralization index
        'n_sbt_holders': 0,    # members with SBT

        # ── Diagnostic failure mode scores ─────────────
        # Updated every tick for real-time monitoring
        'FM1_score': 0,  # 0=GREEN 1=GREEN_b 2=AMBER 3=RED 4=CRITICAL
        'FM2_score': 0,
        'FM3_score': 0,
        'FM4_score': 0,
        'FM5_score': 0,
        'FM6_score': 0,
        'overall_risk': 0.0,

        # ── System parameters (adjustable by Initiator) ─
        'emission_rate_per_participant': 7.5,  # tokens/week
        'burn_fraction':   1.0,   # fraction burned on redeem
        'holding_incentive': 0.0, # tiered redemption bonus
        'K':               8,     # offer variety
        'd':               0.5,   # avg demand per member/week

        # ── Tracking for Initiator decisions ───────────
        'weeks_rho_below_threshold': 0,
        'tick': 0,
    }


"""
========================================================
SECTION 6: POLICY FUNCTIONS
========================================================
Policy functions observe state and return signals.
They are PURE — no side effects, no state mutation.

cadCAD convention:
  def policy_name(params, step, history, state) -> dict
  Returns a dict of signals consumed by state update fns.
"""

# ── POLICY 1: Community Member decisions ──────────────

def policy_community_members(params, step, history, state):
    """
    For each active Community Member, determine:
      1. Participate in association activity? → earn tokens
      2. Redeem tokens for coupon? → spend tokens
      3. Burn badges for rewards? → lose badges, gain tokens
      4. Exit system? → remove from active population

    Returns signals:
      tokens_to_emit:   total new tokens from participation
      redemptions:      number of coupon redemptions
      badges_burned:    number of badges burned
      members_exiting:  list of member IDs exiting
      members_updated:  updated member objects
    """
    members     = state['members']
    coupons_avail = state['coupons_available']
    P_avg       = state['P_avg']
    holding_inc = state['holding_incentive']
    emission_r  = state['emission_rate_per_participant']

    # Compute mean utility for social comparison
    active = [m for m in members if m.is_active]
    if len(active) == 0:
        return {
            'tokens_to_emit': 0,
            'redemptions': 0,
            'badges_burned': 0,
            'members_exiting': [],
            'members_updated': members,
        }

    mean_utility = np.mean([m.utility(P_avg) for m in active])

    tokens_to_emit = 0
    redemptions    = 0
    badges_burned  = 0
    members_exiting = []
    updated_members = []

    for m in members:
        if not m.is_active:
            updated_members.append(m)
            continue

        # --- Decision 1: Participate? ---
        if random.random() < m.p_participate(emission_r):
            # Contribution verified by association
            # (simplified: use average verif_prob)
            avg_verif = np.mean([a.verif_prob
                                 for a in state['associations']
                                 if a.is_active] or [0.8])
            if random.random() < avg_verif:
                m.balance_cvt  += int(emission_r)
                m.weeks_active += 1
                tokens_to_emit += int(emission_r)

        # --- Decision 2: Redeem coupon? ---
        if (coupons_avail > 0
                and m.balance_cvt >= P_avg
                and random.random() < m.p_spend(P_avg,
                                                holding_inc)):
            cost = int(P_avg)
            m.balance_cvt  -= cost
            m.coupons      += 1
            m.total_redemptions += 1
            redemptions    += 1
            coupons_avail  -= 1

        # --- Decision 3: Burn badges? ---
        reward_val = emission_r * 0.5  # half-week reward
        if random.random() < m.p_burn_badge(reward_val,
                                             min_badges=3):
            m.balance_cvt += int(reward_val)
            m.badges      -= 3
            tokens_to_emit += int(reward_val)
            badges_burned  += 3

        # --- Decision 4: Exit? ---
        if random.random() < m.p_exit(mean_utility):
            m.is_active = False
            members_exiting.append(m.id)

        updated_members.append(m)

    return {
        'tokens_to_emit':   tokens_to_emit,
        'redemptions':      redemptions,
        'badges_burned':    badges_burned,
        'members_exiting':  members_exiting,
        'members_updated':  updated_members,
    }


# ── POLICY 2: Association decisions ───────────────────

def policy_associations(params, step, history, state):
    """
    For each active Association, determine:
      1. Organise initiative? → increases member engagement
      2. Issue Badges to verified contributors
      3. Issue SBT to members above participation threshold

    Returns signals:
      badges_to_issue:     total new badges issued
      sbts_to_issue:       member IDs receiving SBT
      initiatives_run:     number of initiatives this tick
      associations_updated: updated association objects
    """
    associations = state['associations']
    members      = state['members']

    n_active_members = sum(1 for m in members
                           if m.is_active
                           and m.weeks_active > 0)

    badges_to_issue  = 0
    sbts_to_issue    = []
    initiatives_run  = 0
    updated_assocs   = []

    for a in associations:
        if not a.is_active:
            updated_assocs.append(a)
            continue

        # --- Decision 1: Organise initiative? ---
        if random.random() < a.p_organise(n_active_members):
            initiatives_run  += 1
            a.initiatives_run += 1

            # Issue badges to verified participants
            for m in members:
                if (m.is_active
                        and m.weeks_active > 0
                        and a.verify_contribution()):
                    m.badges       += 1
                    badges_to_issue += 1
                    a.badges_issued += 1

        # --- Decision 2: Issue SBT to eligible members ---
        for m in members:
            if (m.is_active
                    and not m.has_sbt
                    and m.weeks_active >= a.sbt_threshold):
                m.has_sbt = True
                sbts_to_issue.append(m.id)

        updated_assocs.append(a)

    return {
        'badges_to_issue':     badges_to_issue,
        'sbts_to_issue':       sbts_to_issue,
        'initiatives_run':     initiatives_run,
        'associations_updated': updated_assocs,
    }


# ── POLICY 3: Local Retailer decisions ────────────────

def policy_retailers(params, step, history, state):
    """
    For each active Local Retailer, determine:
      1. Issue new coupons this tick?
      2. Renew coupons at 2-week cycle?

    Returns signals:
      coupons_issued:    total new coupons available
      retailers_updated: updated retailer objects
    """
    retailers   = state['retailers']
    tick        = state['tick']
    redemptions = state.get('Q_t', 0)

    coupons_issued    = 0
    updated_retailers = []

    for r in retailers:
        if not r.is_active:
            updated_retailers.append(r)
            continue

        # --- Decision 1: Issue coupons? ---
        expected_redeem = redemptions / max(len(retailers), 1)
        if random.random() < r.p_issue_coupon(expected_redeem):
            n = r.n_coupons_to_issue(r.tokens_received)
            r.coupons_active += n
            coupons_issued   += n

        # --- Decision 2: Renew at 2-week cycle? ---
        if tick % 2 == 0:
            redeem_2w = r.total_redemptions
            if random.random() < r.p_renew(redeem_2w):
                r.coupons_active  = r.max_coupons
                r.weeks_since_renew = 0
                coupons_issued    += r.max_coupons
            else:
                # Non-renewal → coupon supply drops
                # This is the provider free-rider risk (FM4)
                r.coupons_active  = max(0,
                                        r.coupons_active - 2)
            r.total_redemptions = 0  # reset 2-week counter

        r.weeks_since_renew += 1
        updated_retailers.append(r)

    return {
        'coupons_issued':    coupons_issued,
        'retailers_updated': updated_retailers,
    }


# ── POLICY 4: Initiator decisions ─────────────────────

def policy_initiator(params, step, history, state):
    """
    Initiator monitors system health and adjusts parameters.

    Triggers:
      - Emission reduction if rho < threshold for 2+ weeks
      - Engagement intervention if exit rate > threshold

    Returns signals:
      emission_adjustment: multiplier for emission rate
      new_initiative:      bool, launch new engagement push
    """
    initiator    = state['initiator']
    rho          = state['rho']
    exit_rate    = state['exit_rate_t']
    weeks_low    = state['weeks_rho_below_threshold']

    emission_adj = 1.0   # no change by default
    new_initiative = False

    if initiator.should_adjust_emission(rho, weeks_low):
        emission_adj = 1.0 - initiator.emission_adjustment_factor
        initiator.interventions_made += 1

    if initiator.should_intervene_engagement(exit_rate):
        new_initiative = True
        initiator.interventions_made += 1

    return {
        'emission_adjustment': emission_adj,
        'new_initiative':      new_initiative,
        'initiator_updated':   initiator,
    }


"""
========================================================
SECTION 7: STATE UPDATE FUNCTIONS
========================================================
State update functions consume policy signals and
return the new value for one state variable.

cadCAD convention:
  def update_X(params, step, history, state, signal)
      -> ('variable_name', new_value)
"""

def update_members(params, step, history, state, signal):
    updated = signal.get('members_updated', state['members'])
    return ('members', updated)


def update_associations(params, step, history, state, signal):
    updated = signal.get('associations_updated',
                         state['associations'])
    return ('associations', updated)


def update_retailers(params, step, history, state, signal):
    updated = signal.get('retailers_updated',
                         state['retailers'])
    return ('retailers', updated)


def update_initiator(params, step, history, state, signal):
    updated = signal.get('initiator_updated',
                         state['initiator'])
    return ('initiator', updated)


def update_token_supply(params, step, history,
                        state, signal):
    """
    Update total token supply M_total.
    M(t+1) = M(t) + E(t) - B(t)

    FM3 diagnostic: E(t) - B(t) <= g(t) * M(t)
    """
    E_t = signal.get('tokens_to_emit', 0)
    # Burn = redemptions * coupon_price * burn_fraction
    B_t = int(signal.get('redemptions', 0)
              * state['P_avg']
              * state['burn_fraction'])
    new_M = state['M_total'] + E_t - B_t
    return ('M_total', max(0, new_M))


def update_emission(params, step, history, state, signal):
    E_t    = signal.get('tokens_to_emit', 0)
    adj    = signal.get('emission_adjustment', 1.0)
    new_E  = int(E_t * adj)
    return ('E_t', new_E)


def update_burn(params, step, history, state, signal):
    B_t = int(signal.get('redemptions', 0)
              * state['P_avg']
              * state['burn_fraction'])
    return ('B_t', B_t)


def update_rho(params, step, history, state, signal):
    """
    Burn coverage ratio rho = B(t) / E(t)
    FM3 threshold: rho >= 1 for supply stability
    """
    E_t = max(1, signal.get('tokens_to_emit', 1))
    B_t = int(signal.get('redemptions', 0)
              * state['P_avg']
              * state['burn_fraction'])
    return ('rho', B_t / E_t)


def update_transactions(params, step, history,
                        state, signal):
    return ('Q_t', signal.get('redemptions', 0))


def update_coupons_available(params, step, history,
                              state, signal):
    current  = state['coupons_available']
    issued   = signal.get('coupons_issued', 0)
    redeemed = signal.get('redemptions', 0)
    new_val  = max(0, current + issued - redeemed)
    return ('coupons_available', new_val)


def update_n_active(params, step, history, state, signal):
    members  = signal.get('members_updated', state['members'])
    n_active = sum(1 for m in members if m.is_active)
    return ('N_active', n_active)


def update_phi(params, step, history, state, signal):
    """
    Active contributor rate phi = contributors / N_active
    FM4 threshold: phi >= d / K
    """
    members  = signal.get('members_updated', state['members'])
    active   = [m for m in members if m.is_active]
    if not active:
        return ('phi_t', 0.0)
    contributors = sum(1 for m in active
                       if m.weeks_active > 0
                       and m.balance_cvt > 0)
    return ('phi_t', contributors / len(active))


def update_exit_rate(params, step, history, state, signal):
    exiting  = len(signal.get('members_exiting', []))
    n_active = max(1, state['N_active'])
    return ('exit_rate_t', exiting / n_active)


def update_n_sbt(params, step, history, state, signal):
    members = signal.get('members_updated', state['members'])
    n_sbt   = sum(1 for m in members if m.has_sbt)
    return ('n_sbt_holders', n_sbt)


def update_emission_rate(params, step, history,
                          state, signal):
    adj      = signal.get('emission_adjustment', 1.0)
    new_rate = state['emission_rate_per_participant'] * adj
    return ('emission_rate_per_participant',
            max(1.0, new_rate))


def update_weeks_rho_low(params, step, history,
                          state, signal):
    rho      = state['rho']
    current  = state['weeks_rho_below_threshold']
    threshold = 0.5
    if rho < threshold:
        return ('weeks_rho_below_threshold', current + 1)
    return ('weeks_rho_below_threshold', 0)


def update_tick(params, step, history, state, signal):
    return ('tick', state['tick'] + 1)


def update_diagnostic_scores(params, step, history,
                               state, signal):
    """
    Compute failure mode scores at each tick.
    Scores: 0=GREEN 1=GREEN_b 2=AMBER 3=RED 4=CRITICAL

    Maps diagnostic framework conditions to simulation
    observables. See diagnostic_calculation_layer.tex
    for full specification.

    TODO: implement full scoring logic per diagnostic spec.
    Placeholder returns tuple of all six scores.
    """
    # FM1: Oversupply
    E_t   = state['E_t']
    M_con = (state['P_avg'] * state['Q_t']
             / max(state['V_lower'], 0.01))
    ratio = E_t / max(M_con, 1)
    if   ratio <= 1.0: fm1 = 0
    elif ratio <= 1.5: fm1 = 2
    elif ratio <= 2.5: fm1 = 3
    else:              fm1 = 4

    # FM2: Velocity Trap
    tau = state['tau_bar']
    if   tau > 14: fm2 = 0
    elif tau > 7:  fm2 = 1
    elif tau > 3:  fm2 = 2
    else:          fm2 = 3

    # FM3: Burn/Emission Imbalance
    rho = state['rho']
    if   rho >= 1.0:  fm3 = 0
    elif rho >= 0.5:  fm3 = 2
    elif rho > 0.0:   fm3 = 3
    else:             fm3 = 4

    # FM4: Free-Rider
    phi   = state['phi_t']
    d     = state['d']
    K     = state['K']
    req   = d / max(K, 1)
    fm4   = 0 if phi >= req else 3

    # FM5: Critical Mass
    N      = state['N_active']
    N_star = int(2 * K * d + 1)
    ratio5 = N / max(N_star, 1)
    if   ratio5 >= 2.0: fm5 = 0
    elif ratio5 >= 1.2: fm5 = 1
    elif ratio5 >= 1.0: fm5 = 2
    else:               fm5 = 3

    # FM6: Governance Capture
    gamma_g = state['Gamma']
    if   gamma_g <= 0.3: fm6 = 0
    elif gamma_g <= 0.5: fm6 = 1
    elif gamma_g <= 0.8: fm6 = 2
    else:                fm6 = 3

    # Overall weighted score (weights from diagnostic spec)
    weights = {
        'fm1': 1.5, 'fm2': 1.0, 'fm3': 1.5,
        'fm4': 1.0, 'fm5': 1.0, 'fm6': 0.5
    }
    scores = [fm1, fm2, fm3, fm4, fm5, fm6]
    w      = list(weights.values())
    max_s  = 4 * sum(w)
    overall = sum(s * wt for s, wt in zip(scores, w)) / max_s

    # cadCAD requires returning one variable per function.
    # We pack all scores into a dict and unpack in separate
    # update functions below.
    return ('FM1_score', fm1)


def update_fm2(params, step, history, state, signal):
    tau = state['tau_bar']
    if   tau > 14: return ('FM2_score', 0)
    elif tau > 7:  return ('FM2_score', 1)
    elif tau > 3:  return ('FM2_score', 2)
    else:          return ('FM2_score', 3)


def update_overall_risk(params, step, history,
                         state, signal):
    weights = [1.5, 1.0, 1.5, 1.0, 1.0, 0.5]
    scores  = [state['FM1_score'], state['FM2_score'],
               state['FM3_score'], state['FM4_score'],
               state['FM5_score'], state['FM6_score']]
    max_s   = 4 * sum(weights)
    overall = sum(s * w for s, w in zip(scores, weights))
    return ('overall_risk', overall / max_s)


def update_tau_bar(params, step, history, state, signal):
    """
    Update wealth-weighted average holding time.
    tau_bar = sum_i (M_i / M_total) * tau_i

    Approximation: use distribution from agent states.
    Jensen's inequality note: V >= 1/tau_bar is a lower
    bound on true velocity (see diagnostic spec FM2).
    """
    members = signal.get('members_updated', state['members'])
    active  = [m for m in members
               if m.is_active and m.balance_cvt > 0]
    if not active:
        return ('tau_bar', 7.0)

    M_total = sum(m.balance_cvt for m in active)
    if M_total == 0:
        return ('tau_bar', 7.0)

    # Approximate holding time per agent from balance and
    # redemption history — higher balance relative to
    # spending history → longer holding time
    tau_bar = 0.0
    for m in active:
        weight  = m.balance_cvt / M_total
        # Estimate tau from spending rate
        spend_rate = max(0.1, m.total_redemptions
                         / max(m.weeks_active, 1))
        tau_i   = 7.0 / spend_rate  # days
        tau_bar += weight * tau_i

    return ('tau_bar', max(1.0, tau_bar))


def update_V_lower(params, step, history, state, signal):
    tau_bar = state['tau_bar']
    return ('V_lower', 1.0 / max(tau_bar, 0.1))


"""
========================================================
SECTION 8: CADCAD CONFIGURATION
========================================================
Assemble policy functions and state update functions
into cadCAD partial state update blocks (PSUBs).

Each PSUB is a list of dicts with:
  'policies':   list of policy functions
  'variables':  dict mapping variable names to
                update functions
"""

# ── Parameters (adjustable across simulation runs) ────
PARAMS = {
    # System design parameters
    'emission_rate':    [7.5],   # tokens/week default
    'burn_fraction':    [1.0],   # fraction burned on redeem
    'holding_incentive':[0.0],   # tiered redemption bonus
    'K':                [8],     # offer variety
    'd':                [0.5],   # avg demand/member/week
    'Gamma':            [1.0],   # governance centralization
    # Scenario flags
    'has_burn_mechanism': [True],
    'topology':         ['well_mixed'],  # or 'spatial'
}

# ── Partial State Update Blocks (PSUBs) ───────────────
# Each block runs in sequence at each tick.
# Within a block, all policies run in parallel,
# then all update functions run.

PSUBS = [

    # Block 1: Agent decisions
    {
        'policies': {
            'cm_policy':   policy_community_members,
            'ass_policy':  policy_associations,
            'ret_policy':  policy_retailers,
            'init_policy': policy_initiator,
        },
        'variables': {
            'members':
                update_members,
            'associations':
                update_associations,
            'retailers':
                update_retailers,
            'initiator':
                update_initiator,
            'M_total':
                update_token_supply,
            'E_t':
                update_emission,
            'B_t':
                update_burn,
            'rho':
                update_rho,
            'Q_t':
                update_transactions,
            'coupons_available':
                update_coupons_available,
            'N_active':
                update_n_active,
            'phi_t':
                update_phi,
            'exit_rate_t':
                update_exit_rate,
            'n_sbt_holders':
                update_n_sbt,
            'emission_rate_per_participant':
                update_emission_rate,
            'weeks_rho_below_threshold':
                update_weeks_rho_low,
            'tau_bar':
                update_tau_bar,
            'V_lower':
                update_V_lower,
            'tick':
                update_tick,
            'FM1_score':
                update_diagnostic_scores,
            'FM2_score':
                update_fm2,
            'overall_risk':
                update_overall_risk,
        }
    },
]


"""
========================================================
SECTION 9: RUN CONFIGURATION AND EXECUTION
========================================================
"""

def run_simulation(n_timesteps: int = N_WEEKS,
                   n_runs:      int = N_RUNS) -> pd.DataFrame:
    """
    Configure and execute the cadCAD simulation.
    Returns a pandas DataFrame with one row per tick
    per run, containing all state variables.

    Uses cadCAD 0.5.3 API with Experiment object.
    """
    initial_state = build_initial_state()

    sim_config = config_sim({
        'N': n_runs,
        'T': range(n_timesteps),
        'M': PARAMS,
    })

    exp = Experiment()
    exp.append_configs(
        sim_configs                 = sim_config,
        initial_state               = initial_state,
        partial_state_update_blocks = PSUBS,
    )

    exec_mode    = ExecutionMode()
    exec_context = ExecutionContext(exec_mode.local_mode)
    executor     = Executor(exec_context, exp.configs)

    raw_result, _, _ = executor.execute()
    df = pd.DataFrame(raw_result)
    return df


"""
========================================================
SECTION 10: OUTPUT ANALYSIS AND VISUALISATION
========================================================
"""

def compute_summary_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute summary statistics across Monte Carlo runs.
    Returns mean and std of key metrics per timestep.
    """
    key_metrics = [
        'M_total', 'E_t', 'B_t', 'rho',
        'Q_t', 'N_active', 'phi_t', 'exit_rate_t',
        'tau_bar', 'V_lower', 'n_sbt_holders',
        'FM1_score', 'FM2_score', 'FM3_score',
        'FM4_score', 'FM5_score', 'FM6_score',
        'overall_risk',
    ]
    available = [m for m in key_metrics if m in df.columns]
    summary = (df.groupby('timestep')[available]
                 .agg(['mean', 'std'])
                 .reset_index())
    return summary


def compute_failure_mode_timeline(
        df: pd.DataFrame) -> pd.DataFrame:
    """
    For each run, identify the first timestep at which
    each failure mode reaches RED or CRITICAL (score >= 3).
    Useful for understanding which failure modes manifest
    first and in what order.
    """
    results = []
    for run in df['run'].unique():
        run_df = df[df['run'] == run].sort_values('timestep')
        row = {'run': run}
        for fm in ['FM1_score', 'FM2_score', 'FM3_score',
                   'FM4_score', 'FM5_score', 'FM6_score']:
            if fm not in run_df.columns:
                row[fm + '_first_red'] = None
                continue
            red_weeks = run_df[run_df[fm] >= 3]['timestep']
            row[fm + '_first_red'] = (red_weeks.min()
                                      if len(red_weeks) > 0
                                      else None)
        results.append(row)
    return pd.DataFrame(results)


"""
========================================================
SECTION 11: SCENARIO DEFINITIONS
========================================================
Three baseline scenarios corresponding to the three
case studies from Paper 1. Use these as validation
benchmarks — the simulation should reproduce the
risk profiles computed manually in the paper.
"""

SCENARIO_NLAB4CIT = {
    # Case 1: NLAB4CIT — highest oversupply risk
    # Expected: FM1 CRITICAL, FM3 CRITICAL, FM6 RED
    'emission_rate_per_participant': 7.5,
    'burn_fraction':    0.0,    # no burn mechanism
    'K':                8,
    'd':                0.5,
    'Gamma':            1.0,    # fully centralized
    'has_burn_mechanism': False,
    'N_MEMBERS':        100,
    'N_RETAILERS':      8,
    'N_ASSOCIATIONS':   4,
}

SCENARIO_LIBRARY_OF_THINGS = {
    # Case 2: Library of Things — lowest supply risk
    # Expected: FM1 LOW (E/M_consistent ~ 0.10)
    # FM5 HIGH (item-specific matching)
    'emission_rate_per_participant': 3.5,
    'burn_fraction':    0.0,
    'K':                20,     # many item types
    'd':                1.0,    # daily borrowing
    'Gamma':            0.8,
    'has_burn_mechanism': False,
    'holding_incentive': 5.0,   # escrow forces holding
}

SCENARIO_FOODREBORN = {
    # Case 3: FoodReborn — intermediate risk
    # Expected: FM1 LOW-MEDIUM (anchored emission)
    # FM3 LOW-MEDIUM (coupon burn exists)
    'emission_rate_per_participant': 5.0,
    'burn_fraction':    1.0,    # coupon burn at restaurant
    'K':                5,
    'd':                0.5,
    'Gamma':            1.0,
    'has_burn_mechanism': True,
}


"""
========================================================
SECTION 12: MAIN ENTRY POINT
========================================================
"""

if __name__ == '__main__':
    print("Running token economy simulation...")
    print(f"Parameters: {N_MEMBERS} members, "
          f"{N_ASSOCIATIONS} associations, "
          f"{N_RETAILERS} retailers")
    print(f"Horizon: {N_WEEKS} weeks, "
          f"{N_RUNS} Monte Carlo runs")
    print()

    df = run_simulation(n_timesteps=N_WEEKS, n_runs=N_RUNS)

    print(f"Simulation complete. Output shape: {df.shape}")
    print()

    # Summary statistics
    summary = compute_summary_metrics(df)
    print("Key metrics at week 52 (mean across runs):")
    if not summary.empty:
        last = summary[summary['timestep'] == N_WEEKS - 1]
        for col in ['M_total', 'rho', 'N_active',
                    'phi_t', 'overall_risk']:
            mean_col = (col, 'mean')
            if mean_col in last.columns:
                val = last[mean_col].values
                if len(val) > 0:
                    print(f"  {col}: {val[0]:.3f}")

    # Failure mode timeline
    timeline = compute_failure_mode_timeline(df)
    print()
    print("First week each FM reaches RED (mean across runs):")
    for col in [c for c in timeline.columns
                if '_first_red' in c]:
        val = timeline[col].mean()
        print(f"  {col}: week {val:.1f}" if pd.notna(val)
              else f"  {col}: never")

    print()
    print("Simulation complete.")
    print("Next steps:")
    print("  1. Validate against manual calculations "
          "in Paper 1")
    print("  2. Run three case study scenarios")
    print("  3. Test design interventions "
          "(add burn, reduce emission)")
    print("  4. Generate figures for Paper 2")
