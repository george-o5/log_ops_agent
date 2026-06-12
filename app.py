#!/usr/bin/env python3
"""
LogOps Agentic - Splunk Alert Health Portal
Streamlit dashboard for autonomous AI-driven SIEM rule auditing
"""

import streamlit as st
from splunk_agent import run_audit
from ai_explainer import generate_explanations

# Page configuration
st.set_page_config(
    page_title="🎯 LogOps Agentic — Splunk Alert Health Portal",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def main():
    # Main header
    st.title("🎯 LogOps Agentic — Splunk Alert Health Portal")
    st.caption("Autonomous AI-driven SIEM rule auditing agent for real-time alert health monitoring")
    
    # Button to re-run audit
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 Re-Run Live Agent Audit", type="primary", use_container_width=True):
            st.rerun()
    
    st.divider()
    
    # Run the pipeline
    with st.spinner("Running audit pipeline..."):
        try:
            # Execute core pipeline
            audit_data = run_audit()
            final_results = generate_explanations(audit_data)
            
            # Calculate metrics
            total_alerts = len(final_results)
            red_count = sum(1 for alert in final_results if alert.get('status') == 'RED')
            operational_count = sum(1 for alert in final_results if alert.get('status') in ['AMBER', 'GREEN'])
            
            # Metric cards row
            metric_col1, metric_col2, metric_col3 = st.columns(3)
            
            with metric_col1:
                st.metric(
                    label="📊 Total Alerts Audited",
                    value=total_alerts
                )
            
            with metric_col2:
                st.metric(
                    label="🔴 Misconfigured Rules", 
                    value=red_count,
                    delta=f"{red_count}/{total_alerts}" if total_alerts > 0 else "0/0"
                )
            
            with metric_col3:
                st.metric(
                    label="🟢 Operational Rules",
                    value=operational_count,
                    delta=f"{operational_count}/{total_alerts}" if total_alerts > 0 else "0/0"
                )
            
            st.divider()
            
            # Display each alert in clean cards
            for alert in final_results:
                alert_name = alert.get('name', 'Unknown Alert')
                alert_query = alert.get('query', 'No query available')
                alert_status = alert.get('status', 'UNKNOWN')
                alert_diagnosis = alert.get('diagnosis', 'No diagnosis available')
                
                # Extract index from query for display
                index_name = "Unknown"
                if 'index=' in alert_query:
                    try:
                        index_start = alert_query.find('index=') + 6
                        index_end = alert_query.find(' ', index_start)
                        if index_end == -1:
                            index_end = len(alert_query)
                        index_name = alert_query[index_start:index_end]
                    except:
                        index_name = "Unknown"
                
                # Status badge configuration
                if alert_status == 'RED':
                    status_display = "🔴 RED (Critical)"
                    status_color = "red"
                elif alert_status == 'AMBER':
                    status_display = "🟡 AMBER (Passive)"
                    status_color = "orange"
                elif alert_status == 'GREEN':
                    status_display = "🟢 GREEN (Active)"
                    status_color = "green"
                else:
                    status_display = "⚪ UNKNOWN"
                    status_color = "gray"
                
                # Create card container
                with st.container():
                    # Card header with alert info
                    header_col1, header_col2 = st.columns([3, 1])
                    
                    with header_col1:
                        st.subheader(f"🚨 {alert_name}")
                        st.write(f"**Target Index:** `{index_name}`")
                    
                    with header_col2:
                        st.markdown(f"**Status:** :{status_color}[**{status_display}**]")
                    
                    # SPL Query display
                    st.markdown("**SPL Query:**")
                    st.code(alert_query, language="sql")
                    
                    # AI Diagnosis display
                    if alert_status == 'RED':
                        st.error(f"🤖 **AI Diagnosis:** {alert_diagnosis}")
                    elif alert_status == 'AMBER':
                        st.warning(f"🤖 **AI Diagnosis:** {alert_diagnosis}")
                    else:
                        st.info(f"🤖 **AI Diagnosis:** {alert_diagnosis}")
                    
                    st.divider()
                        
        except Exception as e:
            st.error(f"❌ Pipeline Error: {str(e)}")
            st.info("Please check your configuration and try again.")

if __name__ == "__main__":
    main()