import logging
from typing import Dict, Type, Optional, List
from adapters.base import BaseJobAdapter

# Import all portal adapters
from adapters.microsoft_portal import MicrosoftPortalAdapter
from adapters.visa_portal import VisaPortalAdapter
from adapters.salesforce_portal import SalesforcePortalAdapter
from adapters.adobe_portal import AdobePortalAdapter
from adapters.servicenow_portal import ServiceNowPortalAdapter
from adapters.standard_chartered_portal import StandardCharteredPortalAdapter
from adapters.apple_portal import ApplePortalAdapter
from adapters.akamai_portal import AkamaiPortalAdapter
from adapters.goldman_sachs_portal import GoldmanSachsPortalAdapter
from adapters.nielsen_portal import NielsenPortalAdapter
from adapters.cisco_portal import CiscoPortalAdapter
from adapters.barclays_portal import BarclaysPortalAdapter
from adapters.razorpay_portal import RazorpayPortalAdapter
from adapters.amazon_portal import AmazonPortalAdapter
from adapters.zscaler_portal import ZscalerPortalAdapter
from adapters.nielseniq_portal import NielsenIQPortalAdapter
from adapters.nutanix_portal import NutanixPortalAdapter
from adapters.meesho_portal import MeeshoPortalAdapter
from adapters.everpure_portal import EverpurePortalAdapter
from adapters.thomson_reuters_portal import ThomsonReutersPortalAdapter
from adapters.netapp_portal import NetAppPortalAdapter
from adapters.fnz_portal import FNZPortalAdapter
from adapters.atlassian_portal import AtlassianPortalAdapter
from adapters.jpmc_portal import JPMCPortalAdapter
from adapters.oracle_portal import OraclePortalAdapter
from adapters.amex_portal import AmexPortalAdapter
from adapters.intuit_portal import IntuitPortalAdapter
from adapters.lseg_portal import LSEGPortalAdapter
from adapters.opentext_portal import OpenTextPortalAdapter
from adapters.databricks_portal import DatabricksPortalAdapter
from adapters.paytm_portal import PaytmPortalAdapter
from adapters.amadeus_portal import AmadeusPortalAdapter
from adapters.phonepe_portal import PhonePePortalAdapter
from adapters.citi_portal import CitiPortalAdapter
from adapters.maersk_portal import MaerskPortalAdapter
from adapters.fractal_portal import FractalPortalAdapter
from adapters.cvent_portal import CventPortalAdapter
from adapters.cadence_portal import CadencePortalAdapter
from adapters.expedia_portal import ExpediaPortalAdapter
from adapters.wellsfargo_portal import WellsFargoPortalAdapter
from adapters.innovaccer_portal import InnovaccerPortalAdapter
from adapters.uhg_portal import UHGPortalAdapter
from adapters.nvidia_portal import NvidiaPortalAdapter
from adapters.amd_portal import AMDPortalAdapter
from adapters.bcg_portal import BCGPortalAdapter
from adapters.ibm_portal import IBMPortalAdapter
from adapters.morgan_stanley_portal import MorganStanleyPortalAdapter
from adapters.mckinsey_portal import McKinseyPortalAdapter
from adapters.sprinklr_portal import SprinklrPortalAdapter
from adapters.bank_of_america_portal import BankOfAmericaPortalAdapter
from adapters.tiger_analytics_portal import TigerAnalyticsPortalAdapter
from adapters.paypal_portal import PaypalPortalAdapter
from adapters.google_portal import GooglePortalAdapter
from adapters.bakerhughes_portal import BakerHughesPortalAdapter
from adapters.ericsson_portal import EricssonPortalAdapter
from adapters.siemens_portal import SiemensPortalAdapter
from adapters.ust_portal import USTPortalAdapter
from adapters.bain_portal import BainPortalAdapter
from adapters.pitney_bowes_portal import PitneyBowesPortalAdapter
from adapters.docusign_portal import DocuSignPortalAdapter
from adapters.rippling_portal import RipplingPortalAdapter
from adapters.stripe_portal import StripePortalAdapter
from adapters.micron_portal import MicronPortalAdapter
from adapters.bytedance_portal import ByteDancePortalAdapter
from adapters.grab_portal import GrabPortalAdapter
from adapters.shopee_portal import ShopeePortalAdapter
from adapters.agoda_portal import AgodaPortalAdapter
from adapters.revolut_portal import RevolutPortalAdapter
from adapters.okx_portal import OKXPortalAdapter
from adapters.okta_portal import OktaPortalAdapter
from adapters.telekom_portal import TelekomPortalAdapter
from adapters.paloalto_portal import PaloAltoPortalAdapter
from adapters.freshworks_portal import FreshworksPortalAdapter
from adapters.ukg_portal import UKGPortalAdapter
from adapters.shurutech_portal import ShuruTechPortalAdapter
from adapters.sprouts_portal import SproutsPortalAdapter
from adapters.blackrock_portal import BlackRockPortalAdapter
from adapters.mastercard_portal import MastercardPortalAdapter
from adapters.teradata_portal import TeradataPortalAdapter
from adapters.tenarai_portal import TenaraiPortalAdapter
from adapters.thoughtworks_portal import ThoughtWorksPortalAdapter
from adapters.uber_portal import UberPortalAdapter
from adapters.zoho_portal import ZohoPortalAdapter
from adapters.swiggy_portal import SwiggyPortalAdapter
from adapters.target_portal import TargetPortalAdapter
from adapters.metaforms_portal import MetaformsPortalAdapter
from adapters.cred_portal import CredPortalAdapter
from adapters.zepto_portal import ZeptoPortalAdapter
from adapters.glean_portal import GleanPortalAdapter
from adapters.browserstack_portal import BrowserStackPortalAdapter
from adapters.postman_portal import PostmanPortalAdapter
from adapters.thoughtspot_portal import ThoughtSpotPortalAdapter
from adapters.devrev_portal import DevRevPortalAdapter
from adapters.snowflake_portal import SnowflakePortalAdapter
from adapters.lenovo_portal import LenovoPortalAdapter
from adapters.scispace_portal import SciSpacePortalAdapter
from adapters.palantir_portal import PalantirPortalAdapter
from adapters.mistral_portal import MistralPortalAdapter
from adapters.kraken_portal import KrakenPortalAdapter
from adapters.newrelic_portal import NewRelicPortalAdapter
from adapters.soprasteria_portal import SopraSteriaPortalAdapter
from adapters.vanguard_portal import VanguardPortalAdapter
from adapters.nationwide_portal import NationwidePortalAdapter
from adapters.doordash_portal import DoorDashPortalAdapter

logger = logging.getLogger(__name__)

ALL_ADAPTER_CLASSES: List[Type[BaseJobAdapter]] = [
    MicrosoftPortalAdapter,
    VisaPortalAdapter,
    SalesforcePortalAdapter,
    AdobePortalAdapter,
    ServiceNowPortalAdapter,
    StandardCharteredPortalAdapter,
    ApplePortalAdapter,
    AkamaiPortalAdapter,
    GoldmanSachsPortalAdapter,
    NielsenPortalAdapter,
    CiscoPortalAdapter,
    BarclaysPortalAdapter,
    RazorpayPortalAdapter,
    AmazonPortalAdapter,
    ZscalerPortalAdapter,
    NielsenIQPortalAdapter,
    NutanixPortalAdapter,
    MeeshoPortalAdapter,
    EverpurePortalAdapter,
    ThomsonReutersPortalAdapter,
    NetAppPortalAdapter,
    FNZPortalAdapter,
    AtlassianPortalAdapter,
    JPMCPortalAdapter,
    OraclePortalAdapter,
    AmexPortalAdapter,
    IntuitPortalAdapter,
    LSEGPortalAdapter,
    OpenTextPortalAdapter,
    DatabricksPortalAdapter,
    PaytmPortalAdapter,
    AmadeusPortalAdapter,
    PhonePePortalAdapter,
    CitiPortalAdapter,
    MaerskPortalAdapter,
    FractalPortalAdapter,
    CventPortalAdapter,
    CadencePortalAdapter,
    ExpediaPortalAdapter,
    WellsFargoPortalAdapter,
    InnovaccerPortalAdapter,
    UHGPortalAdapter,
    NvidiaPortalAdapter,
    AMDPortalAdapter,
    BCGPortalAdapter,
    IBMPortalAdapter,
    MorganStanleyPortalAdapter,
    McKinseyPortalAdapter,
    SprinklrPortalAdapter,
    BankOfAmericaPortalAdapter,
    TigerAnalyticsPortalAdapter,
    PaypalPortalAdapter,
    GooglePortalAdapter,
    BakerHughesPortalAdapter,
    EricssonPortalAdapter,
    SiemensPortalAdapter,
    USTPortalAdapter,
    BainPortalAdapter,
    PitneyBowesPortalAdapter,
    DocuSignPortalAdapter,
    RipplingPortalAdapter,
    StripePortalAdapter,
    MicronPortalAdapter,
    ByteDancePortalAdapter,
    GrabPortalAdapter,
    ShopeePortalAdapter,
    AgodaPortalAdapter,
    RevolutPortalAdapter,
    OKXPortalAdapter,
    OktaPortalAdapter,
    TelekomPortalAdapter,
    PaloAltoPortalAdapter,
    FreshworksPortalAdapter,
    UKGPortalAdapter,
    ShuruTechPortalAdapter,
    SproutsPortalAdapter,
    BlackRockPortalAdapter,
    MastercardPortalAdapter,
    TeradataPortalAdapter,
    TenaraiPortalAdapter,
    ThoughtWorksPortalAdapter,
    UberPortalAdapter,
    ZohoPortalAdapter,
    SwiggyPortalAdapter,
    TargetPortalAdapter,
    MetaformsPortalAdapter,
    CredPortalAdapter,
    ZeptoPortalAdapter,
    GleanPortalAdapter,
    BrowserStackPortalAdapter,
    PostmanPortalAdapter,
    ThoughtSpotPortalAdapter,
    DevRevPortalAdapter,
    SnowflakePortalAdapter,
    LenovoPortalAdapter,
    SciSpacePortalAdapter,
    PalantirPortalAdapter,
    MistralPortalAdapter,
    KrakenPortalAdapter,
    NewRelicPortalAdapter,
    SopraSteriaPortalAdapter,
    VanguardPortalAdapter,
    NationwidePortalAdapter,
    DoorDashPortalAdapter,
]

# Build dictionary mapping portal_id to adapter class
ADAPTER_MAP: Dict[str, Type[BaseJobAdapter]] = {}
for cls in ALL_ADAPTER_CLASSES:
    try:
        inst = cls()
        ADAPTER_MAP[inst.portal_id] = cls
    except Exception as e:
        logger.warning(f"Error mapping adapter class {cls}: {e}")

def get_adapter_instance(portal_id: str) -> Optional[BaseJobAdapter]:
    """Returns a newly instantiated adapter for the given portal_id."""
    cls = ADAPTER_MAP.get(portal_id)
    if cls:
        return cls()
    return None

def get_all_registered_portals() -> List[Dict[str, str]]:
    """Returns a list of dicts with portal_id and portal_name for all registered adapters."""
    portals = []
    for cls in ALL_ADAPTER_CLASSES:
        try:
            inst = cls()
            portals.append({
                "portal_id": inst.portal_id,
                "portal_name": inst.portal_name
            })
        except Exception:
            pass
    return portals
