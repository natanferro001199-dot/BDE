"""One-off script to extend taxonomy.json to 300+ nodes and 500+ edges."""
import json
from pathlib import Path

PATH = Path(__file__).parent / "taxonomy.json"
data = json.loads(PATH.read_text(encoding="utf-8"))

existing_ids = {c["id"] for c in data["concepts"]}

NEW_CONCEPTS = [
    # â”€â”€ Geography (GEO-013 to GEO-022) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"GEO-013","label":"Geography","name":"United Kingdom","aliases":["UK","Great Britain"],"description":"Home of Arm Holdings (CPU IP) and semiconductor design firms","criticality":0.86,"properties":{"key_company":"Arm Holdings"}},
    {"id":"GEO-014","label":"Geography","name":"Singapore","aliases":["SG"],"description":"Regional OSAT and wafer fab hub; GlobalFoundries Singapore fab, Micron DRAM fab","criticality":0.84,"properties":{"key_companies":["GlobalFoundries","Micron"]}},
    {"id":"GEO-015","label":"Geography","name":"Ireland","aliases":["IE"],"description":"Intel's European manufacturing base (Fab 24/34 in Leixlip); significant EU chip production","criticality":0.85,"properties":{"key_company":"Intel Leixlip"}},
    {"id":"GEO-016","label":"Geography","name":"Dresden Germany","aliases":["Sachsen","Silicon Saxony"],"description":"Germany's semiconductor hub: GlobalFoundries Fab 1, Infineon, Bosch, future TSMC fab","criticality":0.88,"properties":{"key_companies":["GlobalFoundries","Infineon","Bosch","TSMC planned"]}},
    {"id":"GEO-017","label":"Geography","name":"Kumamoto Japan","aliases":["Kyushu","Japan semiconductor south"],"description":"TSMC's first Japan fab (JASM joint venture with Sony/Denso); 28/22nm production","criticality":0.87,"properties":{"key_fab":"TSMC JASM Fab 1"}},
    {"id":"GEO-018","label":"Geography","name":"India","aliases":["Bharat"],"description":"Emerging semiconductor destination; Tata Electronics and Micron assembly/test fabs announced","criticality":0.80,"properties":{"key_initiative":"India Semiconductor Mission"}},
    {"id":"GEO-019","label":"Geography","name":"Eindhoven Netherlands","aliases":["ASML HQ","Brainport Eindhoven"],"description":"ASML's global headquarters and primary engineering/manufacturing site for EUV scanners","criticality":1.0,"properties":{"key_company":"ASML HQ"}},
    {"id":"GEO-020","label":"Geography","name":"Luhansk Ukraine","aliases":["Ukrainian neon region"],"description":"Ukrainian industrial region that historically housed primary neon purification plants (Cryoin, Ingas)","criticality":0.90,"properties":{"key_product":"neon gas purification"}},

    # â”€â”€ Additional Companies (COMP-061 to COMP-085) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"COMP-061","label":"Company","name":"Infineon Technologies","aliases":["IFX","Infineon"],"description":"German semiconductor maker; power ICs, automotive, security â€” top automotive chip supplier","criticality":0.88,"properties":{"country":"Germany","founded":1999,"ticker":"IFX.DE","revenue_2023_usd_b":16.3}},
    {"id":"COMP-062","label":"Company","name":"NXP Semiconductors","aliases":["NXPI"],"description":"Automotive, IoT and security chips; largest automotive semiconductor maker after Renesas","criticality":0.87,"properties":{"country":"Netherlands","founded":2006,"ticker":"NXPI","revenue_2023_usd_b":13.3}},
    {"id":"COMP-063","label":"Company","name":"Renesas Electronics","aliases":["Renesas"],"description":"Japan's largest chip maker; automotive microcontrollers and SoCs","criticality":0.87,"properties":{"country":"Japan","founded":2010,"ticker":"6723.T","revenue_2023_usd_b":13.1}},
    {"id":"COMP-064","label":"Company","name":"STMicroelectronics","aliases":["STM","ST"],"description":"European IDM: STM8/STM32 MCUs, automotive ICs, SiC power devices","criticality":0.86,"properties":{"country":"Switzerland/France/Italy","founded":1987,"ticker":"STM","revenue_2023_usd_b":17.3}},
    {"id":"COMP-065","label":"Company","name":"Texas Instruments","aliases":["TI","TXNS"],"description":"Analog and embedded processing chips; owns numerous 300mm analog fabs; cash-flow leader","criticality":0.87,"properties":{"country":"USA","founded":1951,"ticker":"TXN","revenue_2023_usd_b":17.5}},
    {"id":"COMP-066","label":"Company","name":"Wolfspeed","aliases":["Cree","WOLF"],"description":"SiC wafer and power device maker; sole US-based SiC substrate manufacturer at scale","criticality":0.90,"properties":{"country":"USA","founded":1987,"ticker":"WOLF","revenue_2024_usd_b":0.81}},
    {"id":"COMP-067","label":"Company","name":"Onsemi","aliases":["ON Semiconductor","ON"],"description":"SiC and power semiconductor devices for EV charging; competes with STM, Infineon","criticality":0.86,"properties":{"country":"USA","founded":1999,"ticker":"ON","revenue_2023_usd_b":8.3}},
    {"id":"COMP-068","label":"Company","name":"Bosch Semiconductors","aliases":["Robert Bosch","Bosch"],"description":"Automotive IDM; SiC power modules; new 300mm fab in Dresden","criticality":0.85,"properties":{"country":"Germany","founded":1886,"revenue_semiconductor_usd_b":2.0}},
    {"id":"COMP-069","label":"Company","name":"Analog Devices","aliases":["ADI"],"description":"Analog/mixed-signal chips for industrial, auto, and communications","criticality":0.85,"properties":{"country":"USA","founded":1965,"ticker":"ADI","revenue_2023_usd_b":12.3}},
    {"id":"COMP-070","label":"Company","name":"Microchip Technology","aliases":["MCHP"],"description":"Microcontrollers, FPGAs, and analog chips for embedded systems","criticality":0.83,"properties":{"country":"USA","founded":1989,"ticker":"MCHP","revenue_2023_usd_b":8.4}},
    {"id":"COMP-071","label":"Company","name":"IMEC","aliases":["Interuniversity Microelectronics Centre"],"description":"Belgium R&D consortium; EUV and sub-2nm research; TSMC/ASML partner","criticality":0.88,"properties":{"country":"Belgium","type":"research institute","founded":1984}},
    {"id":"COMP-072","label":"Company","name":"Cryoin Engineering","aliases":["Cryoin","Ukrainian neon"],"description":"Ukrainian neon gas purifier; one of two main global neon suppliers (Luhansk-based); disrupted post-2022","criticality":0.90,"properties":{"country":"Ukraine","product":"ultra-pure neon"}},
    {"id":"COMP-073","label":"Company","name":"Ingas","aliases":["Mariupol neon","Ukrainian neon 2"],"description":"Ukrainian neon gas supplier (Mariupol); plant destroyed in 2022 war; major supply shock","criticality":0.90,"properties":{"country":"Ukraine","city":"Mariupol","status":"destroyed 2022"}},
    {"id":"COMP-074","label":"Company","name":"Air Liquide","aliases":["AI","AL"],"description":"French industrial gas company; semiconductor-grade gases for fabs; working to replace Ukrainian neon","criticality":0.86,"properties":{"country":"France","founded":1902,"ticker":"AI.PA","revenue_2023_usd_b":27.0}},
    {"id":"COMP-075","label":"Company","name":"Linde plc","aliases":["LIN","Linde"],"description":"Largest industrial gas company; ultra-pure gases for semiconductor fabs worldwide","criticality":0.88,"properties":{"country":"Ireland/Germany","founded":1879,"ticker":"LIN","revenue_2023_usd_b":32.9}},
    {"id":"COMP-076","label":"Company","name":"Murata Manufacturing","aliases":["Murata","6981.T"],"description":"Passive component maker (MLCC capacitors, inductors); critical for all electronic assemblies","criticality":0.88,"properties":{"country":"Japan","founded":1944,"ticker":"6981.T","revenue_2023_usd_b":14.0}},
    {"id":"COMP-077","label":"Company","name":"TDK Corporation","aliases":["TDK","6762.T"],"description":"Passive components, sensors, magnets; NdFeB magnet major supplier","criticality":0.85,"properties":{"country":"Japan","founded":1935,"ticker":"6762.T","revenue_2023_usd_b":13.9}},
    {"id":"COMP-078","label":"Company","name":"Samsung Foundry","aliases":["Samsung LSI Foundry","SF"],"description":"Samsung's contract foundry division; 3nm GAA production; main TSMC competitor","criticality":0.93,"properties":{"country":"South Korea","process":"3nm GAA","parent":"Samsung Electronics"}},
    {"id":"COMP-079","label":"Company","name":"Intel Foundry","aliases":["Intel Foundry Services","IFS","Intel 18A"],"description":"Intel's new foundry business targeting external customers with Intel 18A process (2025)","criticality":0.85,"properties":{"country":"USA","process":"Intel 18A","status":"ramping 2025"}},
    {"id":"COMP-080","label":"Company","name":"TSMC Arizona","aliases":["TSMC Fab 21","JASM"],"description":"TSMC's US fab in Phoenix AZ; N4P production started 2024; N2 planned 2026","criticality":0.90,"properties":{"country":"USA","location":"Phoenix AZ","process":"N4P start 2024"}},
    {"id":"COMP-081","label":"Company","name":"Entegris Microelectronics","aliases":["Entegris","ENTG materials"],"description":"Advanced purity materials: EUV photochemicals, CMP slurries, gas filters; acquired CMC Materials","criticality":0.92,"properties":{"country":"USA","founded":1966,"ticker":"ENTG"}},
    {"id":"COMP-082","label":"Company","name":"Nova Ltd","aliases":["NVMI","Nova Measuring"],"description":"Optical CD and thin-film metrology systems; fast-growing KLA competitor","criticality":0.83,"properties":{"country":"Israel","founded":1993,"ticker":"NVMI","revenue_2023_usd_b":0.52}},
    {"id":"COMP-083","label":"Company","name":"Camtek","aliases":["CAMT"],"description":"2D/3D metrology and inspection for advanced packaging; strong in HBM and CoWoS inspection","criticality":0.84,"properties":{"country":"Israel","founded":1987,"ticker":"CAMT","revenue_2023_usd_b":0.34}},
    {"id":"COMP-084","label":"Company","name":"Onto Innovation","aliases":["ONTO","Nanometrics-Rudolph"],"description":"Process control: overlay, thin-film, and inspection; third player after KLA and AMAT in metrology","criticality":0.81,"properties":{"country":"USA","founded":2019,"ticker":"ONTO","revenue_2023_usd_b":0.98}},
    {"id":"COMP-085","label":"Company","name":"Mattson Technology","aliases":["Mattson","Hua Hong subsidiary"],"description":"Thermal processing (RTP, batch anneal) systems; majority owned by China's Hua Hong group","criticality":0.76,"properties":{"country":"USA","owner":"Hua Hong (China)"}},

    # â”€â”€ Additional Materials (MAT-041 to MAT-065) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"MAT-041","label":"Material","name":"Silicon Carbide Substrate","aliases":["SiC substrate","4H-SiC boule"],"description":"Wide-bandgap substrate for power devices in EVs; supply tightly controlled by Wolfspeed, Coherent","criticality":0.92,"properties":{"bandgap_ev":3.26,"key_use":"EV power inverters"}},
    {"id":"MAT-042","label":"Material","name":"GaN-on-Silicon","aliases":["GaN","gallium nitride on Si"],"description":"Power device substrate grown on silicon; used in chargers, RF, and power supplies","criticality":0.87,"properties":{"key_use":"fast chargers, RF"}},
    {"id":"MAT-043","label":"Material","name":"Glass Substrate","aliases":["glass core substrate","Intel glass substrate"],"description":"Next-gen packaging substrate using glass instead of organic resin; Intel pioneering for 2026+","criticality":0.85,"properties":{"pioneer":"Intel","status":"R&D/early production"}},
    {"id":"MAT-044","label":"Material","name":"ArF Photoresist","aliases":["KrF resist","248nm resist"],"description":"Photoresist for KrF 248nm lithography; used for mature nodes and back-end layers","criticality":0.87,"properties":{"wavelength_nm":248}},
    {"id":"MAT-045","label":"Material","name":"MLCC Capacitor","aliases":["multi-layer ceramic capacitor","ceramic capacitor"],"description":"Passive component essential in every PCB and package; Murata near-monopoly on high-cap types","criticality":0.88,"properties":{"supplier_dominance":"Murata/TDK/Taiyo Yuden"}},
    {"id":"MAT-046","label":"Material","name":"Palladium","aliases":["Pd","palladium wire"],"description":"Used in bond wire for IC packaging; Russia major producer; price spiked during Russia sanctions","criticality":0.86,"properties":{"key_use":"wire bonding","russia_share_pct":40}},
    {"id":"MAT-047","label":"Material","name":"Gold Wire","aliases":["Au wire","gold bond wire"],"description":"Traditional wire bonding material; being replaced by copper wire but still used in high-reliability","criticality":0.82,"properties":{"use":"wire bonding legacy"}},
    {"id":"MAT-048","label":"Material","name":"Copper Wire","aliases":["Cu wire bond","copper bond wire"],"description":"Lower-cost replacement for gold wire bonding; now dominant in consumer electronics","criticality":0.85,"properties":{"use":"wire bonding mainstream"}},
    {"id":"MAT-049","label":"Material","name":"Nitrogen Gas","aliases":["N2","ultra-pure nitrogen"],"description":"Purge and carrier gas used throughout semiconductor fabs; produced locally via PSA/membrane","criticality":0.88,"properties":{"purity":"99.9999%","production":"on-site air separation"}},
    {"id":"MAT-050","label":"Material","name":"Hydrogen Gas","aliases":["H2","ultra-pure hydrogen"],"description":"Carrier gas for epitaxy and anneal steps; produced on-site; explosive handling requirements","criticality":0.87,"properties":{"use":"epitaxy carrier gas"}},
    {"id":"MAT-051","label":"Material","name":"Phosphine","aliases":["PH3","phosphine dopant"],"description":"N-type dopant source gas for CVD and ion implant in silicon; highly toxic","criticality":0.86,"properties":{"formula":"PH3","toxicity":"extremely toxic","use":"n-type doping"}},
    {"id":"MAT-052","label":"Material","name":"Diborane","aliases":["B2H6","boron dopant"],"description":"P-type dopant gas for CVD boron doping; highly toxic and pyrophoric","criticality":0.86,"properties":{"formula":"B2H6","use":"p-type doping"}},
    {"id":"MAT-053","label":"Material","name":"Tungsten Metal","aliases":["W","tungsten fill"],"description":"Metal fill for contacts and vias in logic chips; deposited by CVD using WF6","criticality":0.89,"properties":{"use":"contact/via fill","deposition":"CVD"}},
    {"id":"MAT-054","label":"Material","name":"Copper Interconnect","aliases":["Cu damascene metal","copper wiring"],"description":"Main metal for BEOL wiring layers in all advanced logic chips since 130nm node","criticality":0.93,"properties":{"use":"BEOL wiring","standard_since_nm":130}},
    {"id":"MAT-055","label":"Material","name":"Titanium Nitride","aliases":["TiN","barrier metal"],"description":"Barrier/liner metal deposited by PVD or ALD to prevent copper diffusion into dielectric","criticality":0.88,"properties":{"use":"copper barrier"}},
    {"id":"MAT-056","label":"Material","name":"Fused Silica","aliases":["SiO2 lens","optical quartz","fused quartz"],"description":"Ultra-pure quartz used for DUV optical components (lenses, windows); HERAEUS key supplier","criticality":0.90,"properties":{"use":"DUV optics"}},
    {"id":"MAT-057","label":"Material","name":"Photomask Blank","aliases":["mask blank","chrome-on-glass"],"description":"Glass substrate coated with chromium used to make photomasks; Hoya near-monopoly for EUV blanks","criticality":0.96,"properties":{"euv_supplier_monopoly":"Hoya"}},
    {"id":"MAT-058","label":"Material","name":"Silicon Nitride","aliases":["Si3N4","SiN barrier"],"description":"Barrier and hard mask material; deposited by LPCVD or ALD; used in CMP stop layers","criticality":0.87,"properties":{"formula":"Si3N4"}},
    {"id":"MAT-059","label":"Material","name":"Tantalum","aliases":["Ta","tantalum","Ta barrier"],"description":"Transition metal used as diffusion barrier for copper interconnects; Congo primary source","criticality":0.88,"properties":{"use":"copper barrier","primary_source":"DR Congo","conflict_mineral":True}},
    {"id":"MAT-060","label":"Material","name":"Coltan","aliases":["coltan","columbite-tantalite"],"description":"Ore yielding tantalum and niobium; ~70% mined in DR Congo; conflict mineral designation","criticality":0.85,"properties":{"region":"DR Congo","conflict_mineral":True}},
    {"id":"MAT-061","label":"Material","name":"Lanthanum","aliases":["La","lanthanum oxide"],"description":"Rare earth used in high-k gate dielectrics and optical coatings; China dominates supply","criticality":0.84,"properties":{"use":"high-k dielectric additive","china_dominance":True}},
    {"id":"MAT-062","label":"Material","name":"EUV Source Collector Mirror","aliases":["EUV collector","grazing incidence collector"],"description":"Large ellipsoidal mirror collecting and directing EUV plasma light toward scanner optics; ASML proprietary","criticality":0.99,"properties":{"inside":"ASML EUV scanner source module"}},
    {"id":"MAT-063","label":"Material","name":"DUV Immersion Water","aliases":["ultrapure water","UPW","DI water"],"description":"Ultrapure water used as immersion fluid in 193nm lithography; fab produces 100s of liters/min","criticality":0.90,"properties":{"resistivity_MOhm_cm":18.2,"use":"ArF immersion lithography"}},
    {"id":"MAT-064","label":"Material","name":"NdFeB Permanent Magnet","aliases":["neodymium magnet","rare earth magnet"],"description":"Strongest commercial magnets; used in EV motors, wind turbines, hard drives; China dominates 90%","criticality":0.93,"properties":{"china_share_pct":90,"use":"EV motors, wind turbines"}},
    {"id":"MAT-065","label":"Material","name":"Indium Tin Oxide","aliases":["ITO","transparent conductor"],"description":"Transparent conductive coating for touchscreens, displays; indium supply risk","criticality":0.84,"properties":{"use":"displays, touchscreens","indium_risk":True}},

    # â”€â”€ Additional Processes (PROC-021 to PROC-040) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"PROC-021","label":"Process","name":"Epitaxial Growth","aliases":["epitaxy","Si epitaxy","SiGe epitaxy"],"description":"Growing crystalline semiconductor layer on substrate; used for strained silicon and SiGe channels","criticality":0.90,"properties":{"technique":["CVD","MBE"]}},
    {"id":"PROC-022","label":"Process","name":"Thermal Oxidation","aliases":["gate oxide growth","dry/wet oxidation"],"description":"Growing SiO2 by exposing silicon to oxygen at high temperature; legacy gate dielectric","criticality":0.88,"properties":{"product":"SiO2"}},
    {"id":"PROC-023","label":"Process","name":"Rapid Thermal Processing","aliases":["RTP","spike anneal"],"description":"Short-duration high-temperature annealing for dopant activation without diffusion broadening","criticality":0.87,"properties":{"duration":"seconds","temperature_C":1050}},
    {"id":"PROC-024","label":"Process","name":"Wafer Dicing","aliases":["die singulation","blade dicing","laser dicing"],"description":"Cutting wafer into individual dies by blade saw or laser; Disco dominant equipment supplier","criticality":0.85,"properties":{"methods":["blade","laser"]}},
    {"id":"PROC-025","label":"Process","name":"Wire Bonding","aliases":["gold wire bond","copper wire bond","ball bonding"],"description":"Connecting die bond pads to package leads with fine wire; still dominant in mature-node packages","criticality":0.83,"properties":{"wire_materials":["gold","copper","silver"]}},
    {"id":"PROC-026","label":"Process","name":"Encapsulation","aliases":["molding","over-mold","transfer molding"],"description":"Encapsulating packaged chip in epoxy mold compound to protect from environment","criticality":0.82,"properties":{"material":"epoxy mold compound"}},
    {"id":"PROC-027","label":"Process","name":"Wafer Thinning","aliases":["back-grinding","wafer grinding"],"description":"Grinding wafer backside to reduce thickness for 3D stacking; critical for TSV height reduction","criticality":0.88,"properties":{"target_thickness_um":50}},
    {"id":"PROC-028","label":"Process","name":"Electrochemical Deposition","aliases":["ECD","copper plating","electroplating"],"description":"Electroplating copper into TSV holes and damascene trenches; Lam/Applied dominant suppliers","criticality":0.90,"properties":{"use":"TSV fill, damascene"}},
    {"id":"PROC-029","label":"Process","name":"Laser Ablation","aliases":["laser drilling","laser via formation"],"description":"Using laser to drill vias in organic substrates; critical for HDI substrate fabrication","criticality":0.84,"properties":{"use":"HDI via formation"}},
    {"id":"PROC-030","label":"Process","name":"Under Bump Metallization","aliases":["UBM","under bump metal"],"description":"Metal stack deposited under solder bumps to ensure reliable adhesion and electrical contact","criticality":0.85,"properties":{"stack":"Ti/Cu/Ni"}},
    {"id":"PROC-031","label":"Process","name":"Solder Ball Attach","aliases":["BGA ball attach","solder bumping"],"description":"Attaching solder balls to BGA package pads for PCB mounting","criticality":0.82,"properties":{"use":"BGA packages"}},
    {"id":"PROC-032","label":"Process","name":"Photomask Writing","aliases":["e-beam mask write","mask making"],"description":"Writing IC patterns onto photomask blanks using e-beam or laser direct write","criticality":0.92,"properties":{"tool":"e-beam writer","time":"hours per mask"}},
    {"id":"PROC-033","label":"Process","name":"OPC","aliases":["Optical Proximity Correction","RET","resolution enhancement"],"description":"Computational lithography modifying mask patterns to compensate for diffraction; compute-intensive","criticality":0.94,"properties":{"compute":"months of CPU/GPU time","required_node":"sub-200nm"}},
    {"id":"PROC-034","label":"Process","name":"Atomic Layer Epitaxy","aliases":["ALE","digital epitaxy"],"description":"Monolayer-by-monolayer epitaxial deposition using ALD chemistry; for ultrathin channel layers","criticality":0.85,"properties":{"precision":"monolayer"}},
    {"id":"PROC-035","label":"Process","name":"Die Attach","aliases":["die bond","epoxy die attach","solder die attach"],"description":"Attaching die to substrate or leadframe with epoxy or solder; first step of back-end assembly","criticality":0.83,"properties":{"materials":["silver epoxy","solder","TIM"]}},
    {"id":"PROC-036","label":"Process","name":"Fan-Out Wafer Level Packaging","aliases":["FOWLP","eWLB","FOWLP"],"description":"Reconstituted wafer packaging where RDL connects dies without a substrate","criticality":0.87,"properties":{"no_substrate":True,"key_use":"mobile SoC packages"}},
    {"id":"PROC-037","label":"Process","name":"Wafer Bonding","aliases":["direct wafer bond","fusion bonding"],"description":"Bonding two wafers at oxide or semiconductor surface without adhesive; enables 3D integration","criticality":0.88,"properties":{"types":["oxide-oxide","Si-Si"]}},
    {"id":"PROC-038","label":"Process","name":"Chemical Vapor Infiltration","aliases":["CVI","SiC fiber densification"],"description":"Densification of ceramic composites; used for SiC components in high-temp fab chambers","criticality":0.78,"properties":{"use":"chamber components"}},
    {"id":"PROC-039","label":"Process","name":"Lithographic Simulation","aliases":["TCAD","process simulation","optical modeling"],"description":"Computational modeling of lithography and process steps using TCAD tools","criticality":0.87,"properties":{"tools":["Synopsys Sentaurus","ASML PROLITH"]}},
    {"id":"PROC-040","label":"Process","name":"Burn-in Testing","aliases":["HTOL","high-temperature operating life test","reliability screen"],"description":"Accelerated life testing at elevated voltage/temperature to screen early-failure chips","criticality":0.85,"properties":{"temperature_C":125,"duration_hours":168}},

    # â”€â”€ Additional Equipment (EQUIP-019 to EQUIP-040) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"EQUIP-019","label":"Equipment","name":"Nikon NSR DUV Scanner","aliases":["Nikon stepper","NSR-S635E"],"description":"Nikon's ArF immersion DUV scanner; ASML's main competitor in lithography; losing market share","criticality":0.87,"properties":{"wavelength_nm":193,"company":"Nikon","market_share_pct":10}},
    {"id":"EQUIP-020","label":"Equipment","name":"Canon Lithography System","aliases":["Canon stepper","FPA-8000iW"],"description":"Canon's i-line and KrF steppers; used for mature nodes; third player in lithography","criticality":0.80,"properties":{"company":"Canon","market_share_pct":3}},
    {"id":"EQUIP-021","label":"Equipment","name":"Applied Materials Producer ALD","aliases":["Producer GT","AMAT ALD"],"description":"Applied Materials' ALD system for high-k gate dielectric and 3D NAND liners","criticality":0.89,"properties":{"type":"single-wafer ALD"}},
    {"id":"EQUIP-022","label":"Equipment","name":"TEL Vigus Etch System","aliases":["Vigus","TEL etch"],"description":"Tokyo Electron's conductor and dielectric etch chambers; strong at TSMC and Samsung","criticality":0.88,"properties":{"company":"Tokyo Electron","type":"plasma etch"}},
    {"id":"EQUIP-023","label":"Equipment","name":"Applied Materials VIISta Ion Implanter","aliases":["VIISta","AMAT implant"],"description":"Applied Materials' ion implanter family; competes with Axcelis in advanced node doping","criticality":0.85,"properties":{"company":"Applied Materials","type":"ion implant"}},
    {"id":"EQUIP-024","label":"Equipment","name":"Applied Materials Vantage RTP","aliases":["Vantage","AMAT RTP"],"description":"Applied Materials' rapid thermal processing system for dopant activation anneals","criticality":0.85,"properties":{"type":"RTP"}},
    {"id":"EQUIP-025","label":"Equipment","name":"Ebara CMP Polisher","aliases":["Ebara","Ebara CMP"],"description":"Ebara's CMP polishing system; competes with Applied Materials Mirra in copper CMP","criticality":0.85,"properties":{"company":"Ebara","type":"CMP"}},
    {"id":"EQUIP-026","label":"Equipment","name":"Bruker XRF Metrology","aliases":["Bruker","X-ray fluorescence metrology"],"description":"X-ray fluorescence and XRD metrology for thin film composition and stress measurement","criticality":0.82,"properties":{"type":"XRF/XRD metrology"}},
    {"id":"EQUIP-027","label":"Equipment","name":"Kulicke & Soffa Wire Bonder","aliases":["KLIC bonder","K&S bonder"],"description":"Wire bonding equipment for connecting IC die to package; copper and gold wire capable","criticality":0.84,"properties":{"type":"wire bonding"}},
    {"id":"EQUIP-028","label":"Equipment","name":"Screen Holdings Wet Station","aliases":["Screen wet","wafer cleaning tool"],"description":"Wet chemical cleaning and etching stations; critical for wafer surface preparation","criticality":0.86,"properties":{"type":"wet cleaning/etch"}},
    {"id":"EQUIP-029","label":"Equipment","name":"Lam Research Altus CVD","aliases":["Altus","Lam CVD tungsten"],"description":"Lam's CVD system for tungsten plug and contact fill deposition","criticality":0.87,"properties":{"type":"tungsten CVD"}},
    {"id":"EQUIP-030","label":"Equipment","name":"ASML YieldStar Metrology","aliases":["YieldStar","ASML optical metrology"],"description":"ASML's integrated diffraction-based overlay metrology; feeds alignment correction loops in scanner","criticality":0.92,"properties":{"type":"optical overlay","integration":"in-scanner"}},
    {"id":"EQUIP-031","label":"Equipment","name":"PDF Solutions Cimetrix","aliases":["PDF Solutions","equipment connectivity"],"description":"Equipment data collection and semiconductor analytics software","criticality":0.79,"properties":{"type":"semiconductor analytics"}},
    {"id":"EQUIP-032","label":"Equipment","name":"Entegris FOUP","aliases":["Front Opening Unified Pod","wafer carrier","FOUP"],"description":"Sealed wafer transport container maintaining cleanroom environment between process steps","criticality":0.87,"properties":{"capacity_wafers":25,"material":"HDPE"}},
    {"id":"EQUIP-033","label":"Equipment","name":"Brooks Automation Robot","aliases":["Brooks wafer handler","atmospheric robot"],"description":"Wafer handling robots for load ports and atmospheric transport between tools","criticality":0.84,"properties":{"type":"wafer handler"}},
    {"id":"EQUIP-034","label":"Equipment","name":"Hitachi CD-SEM","aliases":["Hitachi SEM","critical dimension SEM"],"description":"Hitachi's CD-SEM for measuring critical dimensions of patterned features; competes with Applied SEM","criticality":0.88,"properties":{"type":"CD-SEM","company":"Hitachi High-Tech"}},
    {"id":"EQUIP-035","label":"Equipment","name":"Photron High-Speed Camera","aliases":["EUV droplet imaging","tin droplet camera"],"description":"Used in EUV source modules to image and control tin droplet targeting with microsecond precision","criticality":0.88,"properties":{"use":"EUV source tin droplet control"}},
    {"id":"EQUIP-036","label":"Equipment","name":"CML Microsystems Inkjet Head","aliases":["EUV droplet generator","Microdrop"],"description":"Piezo inkjet head generating uniform tin droplets for EUV plasma source","criticality":0.90,"properties":{"use":"EUV tin droplet generation"}},
    {"id":"EQUIP-037","label":"Equipment","name":"Axcelis Purion XE Ion Implanter","aliases":["Purion XE","high-energy implant"],"description":"High-energy ion implanter for deep well and retrograde well implants","criticality":0.85,"properties":{"type":"high-energy ion implant"}},
    {"id":"EQUIP-038","label":"Equipment","name":"Cohu Test Handler","aliases":["Cohu","IC test handler"],"description":"Automated test handlers for IC final test; gravity, pick-and-place, and strip test","criticality":0.80,"properties":{"type":"test handler"}},
    {"id":"EQUIP-039","label":"Equipment","name":"Teradyne ATE","aliases":["Teradyne","automated test equipment","J750"],"description":"Automated test equipment for wafer sort and final test of memory and logic chips","criticality":0.85,"properties":{"company":"Teradyne","type":"ATE"}},
    {"id":"EQUIP-040","label":"Equipment","name":"Advantest ATE","aliases":["Advantest","T2000","93000"],"description":"Japanese ATE maker; strong in memory and mixed-signal test; competes with Teradyne","criticality":0.84,"properties":{"company":"Advantest","type":"ATE"}},

    # â”€â”€ Additional Technology (TECH-021 to TECH-035) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"TECH-021","label":"Technology","name":"Intel 18A Process","aliases":["Intel 18A","RibbonFET","PowerVia"],"description":"Intel's 1.8nm-class process with RibbonFET (GAA) transistors and backside power delivery (PowerVia)","criticality":0.90,"properties":{"transistor_type":"RibbonFET GAA","power_delivery":"backside","target_year":2025}},
    {"id":"TECH-022","label":"Technology","name":"Samsung 3nm GAA","aliases":["SF3","Samsung 3GAE"],"description":"Samsung's 3nm process using Gate-All-Around (MBCFET) transistors; first GAA in production 2022","criticality":0.88,"properties":{"transistor_type":"MBCFET GAA","production_year":2022}},
    {"id":"TECH-023","label":"Technology","name":"NVIDIA NVLink Switch","aliases":["NVSwitch","NVLink Switch"],"description":"NVIDIA's high-bandwidth switch chip enabling all-to-all GPU connectivity in DGX/HGX systems","criticality":0.93,"properties":{"bandwidth_tb_s":3.6,"use":"GPU cluster scale-out"}},
    {"id":"TECH-024","label":"Technology","name":"Coherent Optical Transceiver","aliases":["800G transceiver","1.6T optics","co-packaged optics"],"description":"High-speed optical transceivers for data center spine-leaf interconnect at 800G/1.6T","criticality":0.88,"properties":{"speed_gbps":800,"use":"data center networking"}},
    {"id":"TECH-025","label":"Technology","name":"PCIe 6.0","aliases":["PCIe Gen6","PCI Express 6.0"],"description":"64 GT/s PCIe standard; enables high-bandwidth CPU-GPU and GPU-GPU connectivity","criticality":0.85,"properties":{"speed_gt_s":64,"bandwidth_gb_s":256}},
    {"id":"TECH-026","label":"Technology","name":"Backside Power Delivery","aliases":["BSPDN","backside PDN","PowerVia"],"description":"Routing power to transistors from wafer backside, freeing frontside for signal routing; Intel pioneered","criticality":0.88,"properties":{"pioneer":"Intel PowerVia","benefit":"10-20% density improvement"}},
    {"id":"TECH-027","label":"Technology","name":"Gate-All-Around Transistor","aliases":["GAA","nanosheet FET","nanoribbon"],"description":"Next-gen transistor wrapping gate on all 4 sides of channel nanosheet; enables sub-3nm scaling","criticality":0.95,"properties":{"benefit":"better electrostatic control","vs":"FinFET"}},
    {"id":"TECH-028","label":"Technology","name":"FinFET Transistor","aliases":["FinFET","fin field effect transistor"],"description":"Tri-gate transistor used from 22nm to 3nm; being replaced by GAA at 2nm and below","criticality":0.92,"properties":{"use":"3nm to 22nm nodes","successor":"GAA"}},
    {"id":"TECH-029","label":"Technology","name":"DRAM","aliases":["Dynamic Random Access Memory","DDR5"],"description":"Main system memory for computers; Samsung, SK Hynix, Micron produce >95% globally","criticality":0.94,"properties":{"market_concentration":"3 firms >95%","latest_gen":"DDR5/LPDDR5X"}},
    {"id":"TECH-030","label":"Technology","name":"NAND Flash","aliases":["3D NAND","V-NAND","QLC NAND"],"description":"Non-volatile storage; 3D stacking enables 200+ layer density; Samsung, Kioxia, Micron dominant","criticality":0.90,"properties":{"latest_gen":"3D NAND 200+ layers"}},
    {"id":"TECH-031","label":"Technology","name":"AI Inference Chip","aliases":["inference accelerator","NPU","edge AI"],"description":"Chips optimized for running trained AI models; lower power than training chips; NVIDIA, Qualcomm, Apple","criticality":0.91,"properties":{"use_case":"production AI deployment"}},
    {"id":"TECH-032","label":"Technology","name":"5nm Process Node","aliases":["N5","N5P","5nm"],"description":"TSMC 5nm node; high-volume since 2020; Apple A14, AMD Zen 3; still major revenue driver","criticality":0.95,"properties":{"node_nm":5,"euv":True,"first_production":2020}},
    {"id":"TECH-033","label":"Technology","name":"Autonomous Vehicle SoC","aliases":["AV chip","self-driving chip","automotive AI"],"description":"High-performance SoCs for autonomous driving (NVIDIA DRIVE, Mobileye EyeQ, Qualcomm Snapdragon Ride)","criticality":0.87,"properties":{"key_players":["NVIDIA","Mobileye","Qualcomm"]}},
    {"id":"TECH-034","label":"Technology","name":"Power Semiconductor","aliases":["IGBT","SiC MOSFET","power device"],"description":"High-voltage/current switching devices for EVs, renewable energy, industrial; SiC increasingly dominant","criticality":0.90,"properties":{"key_materials":["Si","SiC","GaN"]}},
    {"id":"TECH-035","label":"Technology","name":"Photonic Integrated Circuit","aliases":["PIC","silicon photonics chip","optical chip"],"description":"Chip integrating optical components (lasers, modulators, detectors) for ultra-high-bandwidth comms","criticality":0.87,"properties":{"use":"data center, telecom, LiDAR"}},

    # â”€â”€ Additional Regulations (REG-011 to REG-015) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    {"id":"REG-011","label":"Regulation","name":"India Semiconductor Mission","aliases":["ISM","Semicon India"],"description":"India government scheme subsidizing semiconductor fabs and OSAT facilities; â‚¹76,000 crore (~$9B)","criticality":0.82,"properties":{"budget_usd_b":9,"country":"India","year":2021}},
    {"id":"REG-012","label":"Regulation","name":"EU Critical Raw Materials Act","aliases":["CRMA","EU raw materials"],"description":"EU law to secure supply of 34 critical raw materials; 10% extraction and 40% processing in EU by 2030","criticality":0.86,"properties":{"year":2024,"country":"EU","materials":34}},
    {"id":"REG-013","label":"Regulation","name":"Korea K-Chips Act","aliases":["K-Chips","Korean semiconductor tax credit"],"description":"Korea's tax credit scheme for semiconductor capex (up to 25% for large firms, 35% for SMEs)","criticality":0.84,"properties":{"country":"South Korea","max_tax_credit_pct":25}},
    {"id":"REG-014","label":"Regulation","name":"Japan Economic Security Promotion Act","aliases":["Japan ESPA","Japan economic security"],"description":"Japan law securing supply chains for 11 critical goods including semiconductors; fab subsidies","criticality":0.85,"properties":{"country":"Japan","year":2022,"critical_goods":11}},
    {"id":"REG-015","label":"Regulation","name":"ITAR","aliases":["International Traffic in Arms Regulations","US arms export"],"description":"US export control for defense-related technologies; some semiconductor equipment classified under ITAR","criticality":0.88,"properties":{"country":"USA","agency":"State Department"}},
]

NEW_EDGES = [
    # Geographic locations for new companies
    {"source":"COMP-061","target":"GEO-006","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-062","target":"GEO-005","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-063","target":"GEO-003","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-064","target":"GEO-006","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-065","target":"GEO-004","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-066","target":"GEO-004","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-067","target":"GEO-004","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-068","target":"GEO-006","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-072","target":"GEO-008","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-073","target":"GEO-008","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-074","target":"GEO-006","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-076","target":"GEO-003","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-077","target":"GEO-003","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-078","target":"GEO-002","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-016","target":"GEO-013","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-071","target":"GEO-005","relation":"LOCATED_IN","properties":{"confidence":1.0,"note":"IMEC based in Leuven Belgium, close to Netherlands"}},

    # SiC supply chain
    {"source":"COMP-066","target":"MAT-041","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.92,"note":"Wolfspeed is primary US SiC substrate supplier"}},
    {"source":"COMP-003","target":"MAT-041","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.85}},
    {"source":"TECH-034","target":"MAT-041","relation":"DEPENDS_ON","properties":{"confidence":0.85,"criticality":0.90}},
    {"source":"TECH-034","target":"MAT-042","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.82}},
    {"source":"MAT-041","target":"GEO-004","relation":"CONTROLS","properties":{"confidence":0.70,"criticality":0.87,"note":"Wolfspeed (USA) controls most SiC substrate capacity"}},

    # Neon supply chain
    {"source":"COMP-072","target":"MAT-010","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.90,"note":"Cryoin was major neon supplier, Luhansk-based"}},
    {"source":"COMP-073","target":"MAT-010","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.90,"note":"Ingas was major neon supplier, Mariupol-based, destroyed 2022"}},
    {"source":"COMP-074","target":"MAT-010","relation":"PRODUCES","properties":{"confidence":0.60,"criticality":0.82,"note":"Air Liquide expanding neon capacity post-Ukraine war"}},
    {"source":"COMP-075","target":"MAT-010","relation":"PRODUCES","properties":{"confidence":0.70,"criticality":0.85,"note":"Linde major industrial gas supplier expanding neon"}},
    {"source":"MAT-010","target":"PROC-003","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.95,"note":"neon gas fills ArF excimer laser cavity"}},
    {"source":"GEO-020","target":"MAT-010","relation":"CONTROLS","properties":{"confidence":0.85,"criticality":0.90,"note":"Luhansk region housed Cryoin neon plant"}},

    # ABF substrate dependencies
    {"source":"COMP-025","target":"GEO-003","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-049","target":"GEO-001","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"COMP-050","target":"GEO-003","relation":"LOCATED_IN","properties":{"confidence":1.0}},
    {"source":"MAT-004","target":"COMP-025","relation":"DEPENDS_ON","properties":{"confidence":0.40,"criticality":0.93}},
    {"source":"MAT-004","target":"COMP-049","relation":"DEPENDS_ON","properties":{"confidence":0.30,"criticality":0.87}},

    # New process edges
    {"source":"PROC-033","target":"COMP-017","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.94,"note":"Synopsys makes primary OPC/RET software"}},
    {"source":"PROC-033","target":"COMP-018","relation":"DEPENDS_ON","properties":{"confidence":0.80,"criticality":0.88,"note":"Cadence also makes OPC tools"}},
    {"source":"PROC-021","target":"COMP-007","relation":"USES","properties":{"confidence":1.0,"criticality":0.89,"note":"AMAT makes epitaxy reactors"}},
    {"source":"PROC-028","target":"EQUIP-029","relation":"USES","properties":{"confidence":1.0,"criticality":0.87}},
    {"source":"PROC-022","target":"EQUIP-024","relation":"USES","properties":{"confidence":1.0,"criticality":0.85}},
    {"source":"PROC-023","target":"EQUIP-024","relation":"USES","properties":{"confidence":1.0,"criticality":0.85}},
    {"source":"PROC-024","target":"EQUIP-013","relation":"USES","properties":{"confidence":1.0,"criticality":0.86}},
    {"source":"PROC-025","target":"EQUIP-027","relation":"USES","properties":{"confidence":1.0,"criticality":0.84}},
    {"source":"PROC-032","target":"COMP-046","relation":"USES","properties":{"confidence":0.80,"criticality":0.88,"note":"Photronics does mask writing"}},
    {"source":"PROC-032","target":"COMP-045","relation":"USES","properties":{"confidence":0.95,"criticality":0.96,"note":"Hoya EUV mask blanks used in mask making"}},

    # Technology node dependencies
    {"source":"TECH-032","target":"PROC-001","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.95}},
    {"source":"TECH-032","target":"COMP-001","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.97}},
    {"source":"TECH-028","target":"PROC-003","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.93,"note":"FinFET nodes 7nm-22nm use DUV multi-patterning"}},
    {"source":"TECH-027","target":"PROC-001","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.97}},
    {"source":"TECH-027","target":"PROC-002","relation":"ENABLES","properties":{"confidence":0.85,"criticality":0.95,"note":"High-NA EUV enables next-gen GAA patterning"}},
    {"source":"TECH-021","target":"PROC-002","relation":"DEPENDS_ON","properties":{"confidence":0.85,"criticality":0.88}},
    {"source":"TECH-021","target":"TECH-027","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.90}},
    {"source":"TECH-021","target":"TECH-026","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"TECH-029","target":"GEO-002","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.94,"note":"South Korea produces ~70% of DRAM"}},
    {"source":"TECH-030","target":"GEO-002","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.85}},
    {"source":"TECH-030","target":"GEO-003","relation":"DEPENDS_ON","properties":{"confidence":0.30,"criticality":0.80,"note":"Kioxia in Japan ~20% of NAND"}},
    {"source":"TECH-031","target":"TECH-009","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.88}},
    {"source":"TECH-031","target":"TECH-032","relation":"DEPENDS_ON","properties":{"confidence":0.60,"criticality":0.87}},
    {"source":"TECH-033","target":"TECH-001","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.85}},
    {"source":"TECH-034","target":"COMP-061","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.86,"note":"Infineon major SiC power device maker"}},
    {"source":"TECH-034","target":"COMP-064","relation":"DEPENDS_ON","properties":{"confidence":0.70,"criticality":0.85}},
    {"source":"TECH-035","target":"TECH-019","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.88}},

    # Regulation edges for new regulations
    {"source":"REG-011","target":"GEO-018","relation":"REGULATES","properties":{"confidence":1.0,"criticality":0.80}},
    {"source":"REG-012","target":"MAT-022","relation":"REGULATES","properties":{"confidence":0.80,"criticality":0.86}},
    {"source":"REG-012","target":"MAT-024","relation":"REGULATES","properties":{"confidence":0.80,"criticality":0.86}},
    {"source":"REG-013","target":"COMP-004","relation":"REGULATES","properties":{"confidence":1.0,"criticality":0.84}},
    {"source":"REG-013","target":"COMP-002","relation":"REGULATES","properties":{"confidence":1.0,"criticality":0.84}},
    {"source":"REG-014","target":"COMP-001","relation":"REGULATES","properties":{"confidence":0.80,"criticality":0.83,"note":"Japan subsidizes TSMC Kumamoto fab"}},
    {"source":"REG-015","target":"COMP-007","relation":"REGULATES","properties":{"confidence":0.70,"criticality":0.82}},
    {"source":"REG-015","target":"COMP-008","relation":"REGULATES","properties":{"confidence":0.70,"criticality":0.82}},

    # Equipment competition and dependencies
    {"source":"EQUIP-019","target":"COMP-001","relation":"DEPENDS_ON","properties":{"confidence":0.80,"criticality":0.87,"note":"TSMC uses some Nikon scanners for non-critical layers"}},
    {"source":"EQUIP-030","target":"EQUIP-001","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.92,"note":"YieldStar metrology feeds NXE scanner alignment"}},
    {"source":"EQUIP-019","target":"EQUIP-003","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.80}},
    {"source":"EQUIP-034","target":"EQUIP-018","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.75,"note":"Hitachi CD-SEM competes with Applied SEM"}},
    {"source":"EQUIP-039","target":"EQUIP-040","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.75}},

    # Company competition edges
    {"source":"COMP-061","target":"COMP-064","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.82,"segment":"power semiconductors"}},
    {"source":"COMP-061","target":"COMP-067","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.80,"segment":"SiC power"}},
    {"source":"COMP-078","target":"COMP-079","relation":"COMPETES_WITH","properties":{"confidence":1.0,"criticality":0.85,"segment":"advanced foundry"}},
    {"source":"COMP-001","target":"COMP-080","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.90,"note":"TSMC Arizona is TSMC subsidiary"}},

    # Material production dependencies
    {"source":"COMP-075","target":"MAT-049","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-075","target":"MAT-050","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.87}},
    {"source":"COMP-074","target":"MAT-049","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.87}},
    {"source":"COMP-074","target":"MAT-012","relation":"PRODUCES","properties":{"confidence":0.80,"criticality":0.86}},
    {"source":"COMP-032","target":"MAT-049","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-032","target":"MAT-012","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.90}},
    {"source":"COMP-076","target":"MAT-045","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-077","target":"MAT-064","relation":"PRODUCES","properties":{"confidence":0.80,"criticality":0.87}},
    {"source":"COMP-077","target":"MAT-045","relation":"PRODUCES","properties":{"confidence":0.80,"criticality":0.84}},
    {"source":"COMP-029","target":"MAT-015","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-029","target":"MAT-016","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},

    # NdFeB magnet supply chain
    {"source":"GEO-007","target":"MAT-064","relation":"CONTROLS","properties":{"confidence":1.0,"criticality":0.93,"note":"China produces ~90% of NdFeB magnets"}},
    {"source":"MAT-024","target":"MAT-064","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.92}},
    {"source":"MAT-025","target":"MAT-064","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.90}},

    # Coltan/tantalum supply chain
    {"source":"GEO-007","target":"MAT-059","relation":"CONTROLS","properties":{"confidence":0.60,"criticality":0.82}},
    {"source":"MAT-060","target":"MAT-059","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.85}},
    {"source":"MAT-059","target":"MAT-054","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.88}},

    # Key process-material-product chains
    {"source":"PROC-003","target":"MAT-056","relation":"USES","properties":{"confidence":1.0,"criticality":0.90,"note":"fused silica lenses in DUV scanners"}},
    {"source":"PROC-001","target":"MAT-062","relation":"USES","properties":{"confidence":1.0,"criticality":0.99}},
    {"source":"PROC-003","target":"MAT-063","relation":"USES","properties":{"confidence":1.0,"criticality":0.90}},
    {"source":"PROC-025","target":"MAT-048","relation":"USES","properties":{"confidence":0.70,"criticality":0.85}},
    {"source":"PROC-025","target":"MAT-047","relation":"USES","properties":{"confidence":0.40,"criticality":0.82}},
    {"source":"PROC-025","target":"MAT-046","relation":"USES","properties":{"confidence":0.80,"criticality":0.86}},
    {"source":"PROC-013","target":"MAT-054","relation":"USES","properties":{"confidence":1.0,"criticality":0.93}},
    {"source":"PROC-013","target":"MAT-055","relation":"USES","properties":{"confidence":1.0,"criticality":0.88}},

    # Fabs at geographic locations
    {"source":"COMP-080","target":"GEO-011","relation":"LOCATED_IN","properties":{"confidence":1.0,"criticality":0.90}},
    {"source":"COMP-001","target":"GEO-017","relation":"LOCATED_IN","properties":{"confidence":1.0,"criticality":0.87,"note":"TSMC JASM fab in Kumamoto Japan"}},
    {"source":"COMP-003","target":"GEO-015","relation":"LOCATED_IN","properties":{"confidence":1.0,"criticality":0.85,"note":"Intel Leixlip fab in Ireland"}},
    {"source":"COMP-019","target":"GEO-016","relation":"LOCATED_IN","properties":{"confidence":1.0,"criticality":0.85,"note":"GlobalFoundries Fab 1 in Dresden"}},

    # Advanced packaging dependencies
    {"source":"PROC-036","target":"MAT-004","relation":"USES","properties":{"confidence":0.60,"criticality":0.83}},
    {"source":"PROC-017","target":"MAT-036","relation":"USES","properties":{"confidence":1.0,"criticality":0.84}},
    {"source":"PROC-035","target":"EQUIP-014","relation":"USES","properties":{"confidence":1.0,"criticality":0.87}},
    {"source":"PROC-027","target":"COMP-042","relation":"USES","properties":{"confidence":0.80,"criticality":0.85}},

    # Hyperscaler AI cluster supply chain
    {"source":"COMP-053","target":"TECH-005","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-054","target":"TECH-006","relation":"PRODUCES","properties":{"confidence":1.0,"criticality":0.85}},
    {"source":"COMP-053","target":"TECH-011","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.95}},
    {"source":"COMP-054","target":"TECH-011","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.95}},
    {"source":"COMP-055","target":"TECH-011","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.95}},
    {"source":"TECH-020","target":"TECH-003","relation":"DEPENDS_ON","properties":{"confidence":0.90,"criticality":0.97}},
    {"source":"TECH-020","target":"TECH-004","relation":"DEPENDS_ON","properties":{"confidence":0.80,"criticality":0.90}},

    # EDA dependencies
    {"source":"COMP-001","target":"COMP-017","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.90,"note":"TSMC certified on Synopsys EDA tools"}},
    {"source":"COMP-001","target":"COMP-018","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"COMP-011","target":"COMP-017","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.92,"note":"NVIDIA chip design uses Synopsys/Cadence"}},
    {"source":"COMP-011","target":"COMP-018","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.90}},
    {"source":"COMP-011","target":"COMP-016","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.95,"note":"NVIDIA GPU uses Arm AXI interconnect IP"}},
    {"source":"COMP-013","target":"COMP-016","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.99,"note":"Qualcomm SoC is ARM-based"}},

    # Material process enable chains
    {"source":"MAT-019","target":"TECH-040","relation":"ENABLES","properties":{"confidence":1.0,"criticality":0.91,"note":"HfO2 gate dielectric enables sub-45nm"}},
    {"source":"MAT-020","target":"TECH-009","relation":"ENABLES","properties":{"confidence":0.85,"criticality":0.87,"note":"Cobalt liner enables reliable Cu interconnect at 7nm"}},
    {"source":"MAT-021","target":"TECH-007","relation":"ENABLES","properties":{"confidence":0.75,"criticality":0.85,"note":"Ruthenium barrier enables sub-3nm Cu interconnect"}},

    # EUV source dependencies (detailed)
    {"source":"EQUIP-018","target":"EQUIP-035","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.88}},
    {"source":"EQUIP-018","target":"EQUIP-036","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.90}},

    # Photomask supply chain
    {"source":"MAT-008","target":"MAT-057","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.96}},
    {"source":"MAT-057","target":"COMP-045","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.96,"note":"Hoya near-monopoly on EUV mask blanks"}},
    {"source":"PROC-032","target":"MAT-057","relation":"USES","properties":{"confidence":1.0,"criticality":0.95}},

    # IMEC research relationships
    {"source":"COMP-071","target":"COMP-006","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.90,"note":"IMEC is primary R&D partner for ASML EUV"}},
    {"source":"COMP-071","target":"COMP-001","relation":"DEPENDS_ON","properties":{"confidence":1.0,"criticality":0.88,"note":"IMEC partners with TSMC on process R&D"}},
]

# Filter out concepts already in taxonomy
new_concept_ids = {c["id"] for c in NEW_CONCEPTS}
existing_ids = {c["id"] for c in data["concepts"]}
added = [c for c in NEW_CONCEPTS if c["id"] not in existing_ids]
data["concepts"].extend(added)

# Filter edges with valid source/target
all_ids = {c["id"] for c in data["concepts"]}
valid_edges = [
    e for e in NEW_EDGES
    if e["source"] in all_ids and e["target"] in all_ids
]
# Deduplicate edges
existing_edge_keys = {(e["source"], e["target"], e["relation"]) for e in data["edges"]}
new_valid = [
    e for e in valid_edges
    if (e["source"], e["target"], e["relation"]) not in existing_edge_keys
]
data["edges"].extend(new_valid)

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

concepts = data["concepts"]
edges = data["edges"]
ids = {c["id"] for c in concepts}
labels = {}
for c in concepts:
    labels[c["label"]] = labels.get(c["label"], 0) + 1
broken = [(e["source"],e["target"]) for e in edges if e["source"] not in ids or e["target"] not in ids]
print(f"Concepts: {len(concepts)}")
print(f"Edges: {len(edges)}")
print("By label:", labels)
print(f"Broken refs: {len(broken)}")
if broken:
    print("Broken:", broken[:5])

