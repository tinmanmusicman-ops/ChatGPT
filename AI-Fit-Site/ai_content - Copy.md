# Supplemental Context
## Global
### Achievements
- Delivered automated HVAC/Thermostat dashboards adding runtime analysis, condenser cost using python, javascript and html.
calculation, weather API integration, and animated Chart.js visuals.
- Streamlined recruiter and employer workflows with resume analyzers, job-lead processors, scoring using Python
tools, and Excel workflow engines.
- Enabled zero-cost workflow orchestration using batch-launched Python automation. Zapier and Make.
- Reduced manual upkeep with self-updating dashboards, Drive push utilities, JSON-driven
configuration engines, and multi-site thermostat tools using Pythoin, c#.net and Android APK
- Improved demos and stakeholder review with automated cycling, dataset animations, UI transitions,
and accessibility-focused layouts.
- Standardized IDs, naming, and schema structures across automation projects to improve clarity and
maintainability.
- Delivered accessible, responsive dashboards with interactive legends, tooltips, high-contrast modes,
and responsive UI components.
- Demonstrated human-guided EI workflows where the human directs architecture and EI executes
development tasks.
- impleneted an audio Chat Bot using the PaymeGPT interface.
## Company: Best Buy Health

### Role
Best Buy Health — Senior Advisor  – Jitterbug Customer Care (2019–2025)

### Situation
At Best Buy Health, call-center agents relied on a manually maintained spreadsheet-driven “wizard” used to guide troubleshooting during live customer calls. Content updates for new firmware and device changes required manually editing a complex spreadsheet and then hand-building corresponding HTML files for a legacy web server. The process was slow, fragile, and difficult to maintain, creating risk that frontline agents would be working from outdated or inconsistent information while a new replacement system was still under development. Because of prior software-development experience, I was pulled from call-center duties to keep the legacy wizard accurate and usable until the organization could fully transition to the new platform.

### What I did
I began by analyzing how the spreadsheet-driven wizard content was being created and discovered there was no consistent structure because multiple contributors maintained it differently. I established a standardized template and formatting rules so all contributors could enter and maintain content in a consistent way. Once the data structure was stable, I developed a VBA macro that parsed the spreadsheet column by column and automatically generated the required HTML output. This allowed the updated wizard content to be produced reliably and loaded into the document management/web system without manual HTML creation, making the process repeatable and maintainable by others.

### Tools / systems
Microsoft Excel with VBA for automation and HTML generation; SharePoint for repository and document management; Git for version control and storage of code and generated HTML structures; standard workstation environment leveraging prior software-development experience to design and implement the automation workflow.

### Result
The project was originally planned as a manual six-month effort and later extended to ten months due to the expected workload of maintaining the legacy wizard. By automating the spreadsheet-to-HTML conversion process, a one-to-two-day manual update cycle for each spreadsheet was reduced to approximately two minutes. This allowed the team to keep the legacy system accurate and current throughout the transition period while significantly reducing manual effort, delay, and risk of inconsistency.

### Evidence / artifacts
Version-controlled SharePoint library tracking spreadsheet changes and updates; Git repository containing VBA automation code and generated HTML structures; standard operating procedure (SOP) documentation for maintaining properly formatted spreadsheets; and the deployed HTML wizard files hosted on the internal web/document system.

### Notes / caveats
The project began with little standardization, as multiple contributors maintained spreadsheets using their own preferred structures. Establishing a shared template and gaining alignment across stakeholders was a necessary first step before automation could be introduced. I was asked to take on the work after being identified internally as having prior software-development experience and a pattern of suggesting process improvements from within the call center. The assignment was to maintain a legacy wizard while a replacement system was being developed, meaning the solution I automated would ultimately be phased out. During the process, it became clear that many of the limitations attributed to the existing web and HTML tooling were not technical constraints but unexplored implementation possibilities. Even so, once the organization committed to a replacement platform, the role of this work remained stabilization and continuity rather than long-term system ownership.

## Company: Tyler Technologies

### Project: Adobe Central Output Server in-house forms framework ("TIMDocs" / "Tyler Forms")
- Rebuilt the document/forms output solution to eliminate third-party agent dependency and bring form-generation control back in-house. (candidate-provided)
- Studied Adobe Central Output Server documentation, identified underused native capabilities, and restructured processing to replace third-party JavaScript-driven agents with native platform features. (candidate-provided)
- Reduced annual licensing/renewal costs by over $500,000 while improving flexibility and long-term control over form behavior. (candidate-provided)

### Role
Tyler Technologies — Forms/Automation/Software Development

### Situation
At Tyler Technologies, the existing document and forms output solution relied on third-party agents due to licensing limitations with Adobe Central Pro Output Server. These external providers controlled implementation and functionality, and the organization had no direct access to underlying code or flexibility to modify form behavior to meet evolving municipal and client needs. This created operational risk and limited the ability to adapt or improve form generation workflows, forcing the organization to evaluate whether the current solution could remain viable or if a more controllable and flexible approach was required for long-term stability and customization.

### What I did
I conducted a deep technical review of Adobe Central Output Server by studying the full system documentation to understand both how it was currently being used and how it could be maximized within the existing licensing constraints. Through this analysis, I determined that the organization was significantly underutilizing the platform’s native capabilities and that many functions being handled by third-party agents could be performed directly within the licensed system. By identifying redundant external dependencies and demonstrating how the existing solution could be configured and used as originally designed, I established a path for bringing form-generation control back in-house while improving flexibility and reducing reliance on external providers.

### Tools / systems
Adobe Central Pro Output Server and its internal processing agents for document and form generation; external definition/configuration files for data tagging, extraction, and formatting; restructuring of existing rule-based job processing to replace third-party JavaScript-driven agents with native platform capabilities; standard workstation development environment supporting analysis and implementation of the revised in-house solution.

### Result
By restructuring the solution to fully utilize Adobe Central Output Server’s native capabilities, the organization eliminated reliance on the third-party provider and reduced annual licensing and renewal costs by over $500,000. Bringing the solution fully in-house restored direct control over form-generation logic and enabled the team to develop customized, more flexible, and robust document solutions tailored to evolving municipal and client requirements.

### Evidence / artifacts
Production configuration and definition files used within Adobe Central Output Server; deployed internal forms solution adopted organization-wide and later known as “Tyler Forms”; internally referred to by colleagues as “TIMDocs” following implementation; live system outputs and continued operational use of the in-house framework as the document-generation standard.

### Notes / caveats
This initiative was largely self-directed, with proof-of-concept development completed outside normal core responsibilities due to both personal interest and the strategic importance of regaining control over the forms framework. Work was conducted within the constraints of an existing Adobe licensing agreement, requiring full compliance with licensed capabilities while maximizing native functionality. Although third-party PDF generation still remained necessary at the time due to licensing limits, the core document-generation framework was successfully brought in-house. The primary risk was whether the organization could transition away from entrenched third-party dependencies without disrupting production workflows. By thoroughly studying official documentation and leveraging the mature, well-supported Adobe Central platform, it became clear that many limitations attributed to the system were due to underutilization rather than technical constraint. The resulting solution demonstrated that the existing platform, when fully understood and properly configured, could deliver the required flexibility and control without external intermediaries.

### Project: DocOrigin Replacement Initiative

### Situation
Adobe announced the end-of-life of Adobe Central Output Server, the core platform supporting Tyler Technologies’ internal forms and document-generation framework. The proposed replacement product from Adobe did not provide feature parity or the flexibility required to support existing municipal and client form workflows. This created significant long-term operational risk, as the organization depended heavily on the existing output infrastructure. With several years before end-of-life, the objective became identifying and engineering a viable replacement that could replicate or exceed existing capabilities while preserving continuity for current production systems. I was moved from implementation support into a software-development role to evaluate alternatives and help design a forward path for replacing the legacy forms framework.

### What I did
After identifying a potential replacement platform, I initiated direct engagement with the vendor to evaluate whether their product could serve as a functional successor to Adobe Central Output Server. Using a provided license and development environment, I conducted a technical evaluation of their framework and determined that while its architecture differed significantly from our existing solution, it was flexible enough to be adapted. I collaborated directly with the vendor’s engineering and leadership teams to explore modifications that would allow the platform to replicate the behavior and structure of our current forms framework. By aligning their system capabilities with our existing data structures, workflows, and output requirements, I began engineering a migration path that could preserve continuity while transitioning away from the end-of-life Adobe platform.

### Tools / systems
DocOrigin document and forms engine (replacement platform under evaluation); Adobe Central Output Server (existing production system maintained during transition planning); XML and XSLT-based transformation logic from existing Tyler Forms outputs; vendor-provided development and evaluation environment; collaborative engineering work with DocOrigin vendor team to extend platform capabilities, including adding support for required transformation and formatting features to align with existing production workflows.

### Result
The evaluation and proof of concept led to a formal agreement with the DocOrigin vendor to tailor their platform to meet Tyler Technologies’ specific requirements and serve as the long-term replacement for the end-of-life Adobe Central Output Server solution. I was assigned as the lead developer and technical point person for the replacement initiative, responsible for engineering the new framework, collaborating with vendor engineers on required system modifications, and ensuring continuity between the legacy and future platforms. This established a viable migration path, secured a sustainable forms infrastructure moving forward, and positioned me as the primary liaison between internal stakeholders, production systems, and the vendor throughout the transition planning and development process.

### Evidence / artifacts
Team Foundation Server (TFS) project repository containing the replacement forms framework under source control; structured file and configuration framework designed for internal development and maintenance; proof-of-concept and production-ready DocOrigin-based form solution integrated into the software development lifecycle; internal adoption of the new framework enabling stakeholders and developers to manage and extend form outputs within the controlled source environment.

### Notes / caveats
Because of fundamental architectural differences between the legacy Adobe Central environment and the replacement DocOrigin platform, there was no viable path for automated conversion of existing form libraries. Migration therefore required structured, phased manual conversion of legacy libraries into the new framework. While initially viewed as a potential obstacle, this constraint became an opportunity to redesign and enhance the form architecture using an open XML structure and JavaScript-based logic, significantly increasing flexibility and long-term maintainability. I served as the primary technical evaluator and proof-of-concept lead, working directly with senior management, internal stakeholders, and the vendor to determine feasibility, demonstrate capabilities, and guide implementation decisions. This role required balancing ongoing support for the legacy system with forward engineering of the replacement platform, ultimately positioning the new framework as a sustainable evolution of the organization’s forms infrastructure. A consistent theme throughout the effort was that deep understanding of platform documentation revealed capabilities that made the transition achievable—reinforcing the importance of fully understanding a system before assuming its limitations.

### Project: Output Format Migration to XML

### Project/Initiative:
Migration of legacy print image, flat file, and CSV outputs to standardized XML with XSLT transformation framework.

### Situation:
The legacy platform was evolving toward a next-generation release, but its output framework was fragmented and built on older formats (print images, fixed-position flat files, and module-specific CSVs), with no consistent standard across modules or customer deployments. Output behavior varied by software version and by whatever internal or third-party forms tooling a customer used, which made upgrades and consistent rendering difficult. The strategic direction was to standardize output into XML, but the legacy system could often only emit XML in a raw or loosely structured way that wasn’t presentation-ready. The core challenge was enabling a reliable XML-based pipeline without requiring extensive code rewrites across the aging platform.

### What I did:
I evaluated each existing output format across departments to confirm it met basic XML encoding and structural standards and could support runtime transformation. Working module by module, I partnered with teams to analyze their outputs and then designed and built a reusable library of XSLT stylesheets capable of transforming raw or loosely structured XML into standardized, presentation-ready formats required by the forms solution. I created a centralized repository for these transformations so they could be applied consistently across outputs, enabling a repeatable migration path. Once the XSLT framework and repository were established, converting additional outputs to XML became a structured, scalable process rather than requiring extensive code rewrites in the legacy platform.

### Tools/Systems:
Adobe Central Output Server and XML Import utilities; XSLT stylesheet development and transformation libraries; NXSLT (.NET compiled XSLT processor) for large-file and high-volume transformations; XML encoding/structure validation tools; legacy software output streams converted to XML; LPR/data transfer mechanisms moving output from core application to forms server; Windows/.NET environment supporting compiled transformation and memory management; Team Foundation Server (TFS) for source control.

### Result:
The result was a full migration of Munis software output from fragmented legacy formats to a standardized XML-based framework. By building the XSLT transformation library incrementally and implementing changes module by module, we were able to stabilize each conversion before moving to the next, allowing us to identify and resolve underlying software limitations as they surfaced. Over roughly two years, this phased approach enabled a controlled, low-risk transition to XML across the platform, creating a consistent, scalable output architecture that improved flexibility for forms processing and future system evolution.

### Evidence/Artifacts:
All transformation code, XSLT libraries, and related configuration files were maintained under source control in Team Foundation Server (TFS). A structured installation package was created to deploy the standardized XML/XSLT transformation framework and default file set across environments, ensuring consistent implementation and repeatability across modules and customer installations.

### Notes / caveats
There was initial resistance at the module level, as many product managers aimed to minimize changes and simply produce usable output with minimal redevelopment. Attempts to enforce fully structured, modernized output formats revealed limitations within the legacy codebase. To prevent these issues from stalling progress, the strategy shifted to prioritizing well-formed XML output over perfectly structured content, allowing transformation logic to handle normalization and formatting downstream. By leveraging a highly configurable XSLT library capable of multi-pass restructuring and attribute-level control, even loosely structured or raw XML dumps could be standardized and transformed into production-ready formats. The primary lesson learned was to reduce friction wherever possible when modernizing legacy systems—accepting imperfect upstream data while engineering flexible downstream transformation provided a faster, more scalable path to modernization.

## Company: Tukey's Home and Land

Falmouth ME | June 1995 – July 1997
- Started as landscaper and gardener, performing routine grounds maintenance and seasonal work
- Promoted to General Manager of Operations based on reliability and problem-solving
- Scheduled crews, coordinated daily work, and ensured jobs were completed on time
- Converted company records from a paper-based system to QuickBooks for accounting and job tracking
- Managed materials, basic budgeting, and client communication
- Maintained quality standards while balancing cost, time, and labor

### Project: QuickBooks records migration (paper -> QuickBooks)
- Migrated paper-based records into QuickBooks to improve accounting accuracy and job tracking. (candidate-provided)
- Set up a consistent structure (customers/jobs/categories) to make data entry and reporting repeatable. (candidate-provided)
- Standardized the workflow so ongoing updates did not depend on one person. (candidate-provided)

## Company: Frazier Farms

Oceanside, CA | February 2021 – September 2021
- Worked as part-time dishwasher and kitchen support in a high-volume food service environment
- Maintained cleanliness and sanitation of dishes, utensils, and kitchen work areas
- Assisted kitchen staff with basic prep, organization, and back-of-house tasks

## Company: Walmart - Electronics Sales Associate

Oceanside, CA | February 2018 – September 2019
- Increased customer satisfaction by 50% by managing the Photo Center and driving targeted
technology improvements.

## Company: TIMDOC Solutions - Owner

Portland, ME | March 2017 – February 2018
- Delivered workflow and home-automation solutions tailored to client needs.
