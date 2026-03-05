"""
APScheduler-based cron scheduler for periodic tasks.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
from app.core.settings import settings
from app.cron.jobs.cleanup import run_sync_job

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler: BackgroundScheduler = None


def start_scheduler():
    """
    Initialize and start the background scheduler.
    Runs periodic jobs without blocking the main server.
    """
    global scheduler
    
    if not settings.CRON_ENABLED:
        logger.info("Cron jobs disabled in settings")
        return
    
    if scheduler is not None:
        logger.warning("Scheduler already running")
        return
    
    try:
        scheduler = BackgroundScheduler(daemon=True)
        
        # Add GitHub sync job - runs every 5 minutes
        scheduler.add_job(
            run_sync_job,
            trigger=IntervalTrigger(minutes=5),
            id="github_commits_sync",
            name="Sync GitHub Commits",
            replace_existing=True,
            max_instances=1  # Prevent concurrent runs
        )
        
        scheduler.start()
        logger.info("✅ Cron scheduler started successfully (GitHub sync every 5 minutes)")
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {str(e)}")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    global scheduler
    
    if scheduler is not None:
        try:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {str(e)}")
        finally:
            scheduler = None

