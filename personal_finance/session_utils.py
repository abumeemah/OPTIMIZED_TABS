import uuid
from datetime import datetime
from flask import session, has_request_context
import logging
from utils import logger

# All users must be authenticated - no anonymous sessions

def get_session_id():
    """Get the current session ID for authenticated users only."""
    try:
        if not has_request_context():
            return 'no-request-context'
            
        return session.get('sid', 'no-session-id')
    except Exception as e:
        logger.error(f"Error getting session ID: {str(e)}")
        return 'session-error'

# All sessions are authenticated

# All users must be authenticated

def update_session_language(language):
    """Update the session language."""
    try:
        if not has_request_context():
            return False
            
        if language in ['en', 'ha']:
            session['lang'] = language
            session.permanent = False  # Non-permanent session
            session['last_activity'] = datetime.utcnow()  # Update activity
            logger.info(f"Updated session language to: {language}")
            return True
        else:
            logger.warning(f"Invalid language code: {language}")
            return False
    except Exception as e:
        logger.error(f"Error updating session language: {str(e)}")
        return False

def get_session_language():
    """Get the current session language."""
    try:
        if not has_request_context():
            return 'en'
            
        return session.get('lang', 'en')
    except Exception:
        return 'en'

def extend_session():
    """Extend the session by updating last_activity."""
    try:
        if not has_request_context():
            return
            
        session.permanent = False  # Ensure 30-minute timeout
        session['last_activity'] = datetime.utcnow()  # Update activity
        session.modified = True
    except Exception as e:
        logger.error(f"Error extending session: {str(e)}")

def get_session_info():
    """Get session information for debugging."""
    try:
        if not has_request_context():
            return {'error': 'No request context'}
            
        return {
            'sid': session.get('sid'),
            'is_authenticated': True,  # All sessions are now authenticated
            'lang': session.get('lang', 'en'),
            'last_activity': session.get('last_activity'),
            'permanent': session.permanent
        }
    except Exception as e:
        logger.error(f"Error getting session info: {str(e)}")
        return {'error': str(e)}
