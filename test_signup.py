import asyncio
import sys
sys.path.insert(0, 'backend/shared')
sys.path.insert(0, 'backend/services/auth-service')

async def test_signup():
    from routers.auth import signup, SignupRequest
    
    request = SignupRequest(
        company_name="TenantS200",
        email="admin@S200.com",
        password="password2026",
        organisation_type="PRODUCER",
        plan_tier="STARTER"
    )
    
    try:
        response = await signup(request)
        print(f"SUCCESS: {response}")
        return True
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_signup())
    sys.exit(0 if result else 1)
